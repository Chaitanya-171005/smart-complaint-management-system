import logging

from django.db import IntegrityError, transaction

from .models import User

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
