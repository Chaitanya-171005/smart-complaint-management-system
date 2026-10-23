import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, login
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import LoginThrottle, SecurityEvent, User
from .security_log import record_event

logger = logging.getLogger(__name__)


class RegistrationError(Exception):
    """Registration failed for a reason other than a duplicate email.

    Carries no details meant for the visitor: show a generic message.
    """


def register_complainant(*, full_name, email, password, user_type, hostel_block="", hostel_room=""):
    """Create a Complainant account (REQ-AUTH-01, BR-04).

    Returns True if an account was created, False if the email is already
    registered. The caller must give the same response either way so the
    result does not reveal whether an account exists. Uniqueness is enforced by
    the database constraint, so concurrent duplicate submissions create one
    account only. An IntegrityError that is not a duplicate email raises
    RegistrationError (never reported as a duplicate). The role is fixed here
    and never taken from input.
    """
    email = email.strip().lower()
    if User.objects.filter(email__iexact=email).exists():
        return False
    try:
        with transaction.atomic():
            User.objects.create_user(
                email=email,
                password=password,  # hashed by Django (set_password)
                full_name=full_name,
                user_type=user_type,
                hostel_block=hostel_block,
                hostel_room=hostel_room,
                role=User.Role.COMPLAINANT,
            )
    except IntegrityError as exc:
        # Expected: another request registered the same email between our check and
        # our insert, and the database unique constraint refused ours. Anything else
        # (a different constraint, a bad value) is a real fault: log it and fail.
        if User.objects.filter(email__iexact=email).exists():
            return False
        logger.exception("Unexpected integrity failure during registration")
        raise RegistrationError from exc
    return True


# ---------------------------------------------------------------------------
# Login and temporary lockout (B02, REQ-AUTH-02)
# ---------------------------------------------------------------------------
LANDING_URL_NAMES = {
    User.Role.COMPLAINANT: "accounts:landing_complainant",
    User.Role.STAFF: "accounts:landing_staff",
    User.Role.HEAD: "accounts:landing_head",
    User.Role.ADMIN: "accounts:landing_admin",
}


def landing_url_name(role):
    """Landing page for the user's current role."""
    return LANDING_URL_NAMES[role]


@dataclass
class LoginResult:
    status: str  # "ok", "invalid" or "locked"
    user: object = None


def normalize_identifier(email):
    return (email or "").strip().lower()[:254]


def is_locked(email, now):
    until = (
        LoginThrottle.objects.filter(email=email)
        .values_list("locked_until", flat=True)
        .first()
    )
    return bool(until and until > now)


def register_failure(email, now):
    """Count a failed attempt. Returns True if this failure started a lockout."""
    window = timedelta(minutes=settings.LOGIN_FAILURE_WINDOW_MINUTES)
    lockout = timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
    with transaction.atomic():
        throttle, _ = LoginThrottle.objects.select_for_update().get_or_create(email=email)
        if throttle.window_start is None or now - throttle.window_start > window:
            throttle.failure_count = 0
            throttle.window_start = now
        throttle.failure_count += 1
        started = throttle.failure_count >= settings.LOGIN_MAX_FAILURES
        if started:
            throttle.locked_until = now + lockout
            throttle.failure_count = 0
            throttle.window_start = None
        throttle.save()
    return started


def clear_failures(email):
    LoginThrottle.objects.filter(email=email).delete()


def attempt_login(request, email, password):
    """Authenticate on the server with lockout enforcement (REQ-AUTH-02).

    Refuses authentication during an active lockout even if the password is
    right. Wrong passwords and unknown emails give the same "invalid" result.
    """
    now = timezone.now()
    email = normalize_identifier(email)

    if is_locked(email, now):
        record_event(SecurityEvent.EventType.LOGIN_BLOCKED, identifier=email)
        return LoginResult("locked")

    user = authenticate(request, username=email, password=password)
    if user is None:
        known = User.objects.filter(email__iexact=email).first()
        record_event(SecurityEvent.EventType.LOGIN_FAILURE, user=known, identifier=email)
        if register_failure(email, now):
            record_event(
                SecurityEvent.EventType.LOGIN_LOCKOUT,
                user=known,
                identifier=email,
                detail=f"locked for {settings.LOGIN_LOCKOUT_MINUTES} minutes",
            )
            return LoginResult("locked")
        return LoginResult("invalid")

    clear_failures(email)
    login(request, user)
    record_event(SecurityEvent.EventType.LOGIN_SUCCESS, user=user, identifier=email)
    return LoginResult("ok", user)
