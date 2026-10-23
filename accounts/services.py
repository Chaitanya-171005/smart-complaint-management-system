from django.db import IntegrityError, transaction

from .models import User


def register_complainant(*, full_name, email, password, user_type, hostel_block="", hostel_room=""):
    """Create a Complainant account (REQ-AUTH-01, BR-04).

    Returns True if an account was created, False if the email is already
    registered. The caller must give the same response either way so the
    result does not reveal whether an account exists. Uniqueness is enforced by
    the database constraint, so concurrent duplicate submissions create one
    account only. The role is fixed here and never taken from input.
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
    except IntegrityError:
        return False
    return True
