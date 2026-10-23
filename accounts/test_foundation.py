import pytest
from django.contrib.auth import get_user_model


@pytest.mark.django_db
def test_custom_user_defaults_to_complainant_and_hashes_password():
    user = get_user_model().objects.create_user(
        email="a@b.com", password="Campus123", full_name="A B"
    )
    assert user.role == "COMPLAINANT"
    assert user.check_password("Campus123")
    assert user.password != "Campus123"


@pytest.mark.django_db
def test_email_is_login_field_and_unique():
    from django.db import IntegrityError

    U = get_user_model()
    assert U.USERNAME_FIELD == "email"
    U.objects.create_user(email="x@y.com", password="Campus123", full_name="X")
    with pytest.raises(IntegrityError):
        U.objects.create_user(email="x@y.com", password="Campus123", full_name="Y")
