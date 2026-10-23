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


@pytest.mark.django_db
def test_create_superuser_defaults():
    u = get_user_model().objects.create_superuser(
        email="root@b.com", password="Campus123", full_name="Root"
    )
    assert u.is_staff and u.is_superuser and u.role == "ADMIN"


@pytest.mark.django_db
@pytest.mark.parametrize("flag", ["is_staff", "is_superuser"])
@pytest.mark.parametrize("value", [False, None, 0])
def test_create_superuser_rejects_explicit_false_flags(flag, value):
    U = get_user_model()
    with pytest.raises(ValueError):
        U.objects.create_superuser(
            email="root@b.com", password="Campus123", full_name="Root", **{flag: value}
        )
    assert not U.objects.filter(email="root@b.com").exists()


def test_parse_hosts_trims_and_ignores_empty():
    from scms.settings import parse_hosts

    assert parse_hosts(" localhost , 127.0.0.1,, ,example.com ") == [
        "localhost",
        "127.0.0.1",
        "example.com",
    ]
    assert parse_hosts("") == []
    assert parse_hosts(" , ") == []


def test_allowed_hosts_setting_has_no_blank_or_padded_entries(settings):
    assert all(h and h == h.strip() for h in settings.ALLOWED_HOSTS)


def test_default_auto_field_is_bigautofield(settings):
    assert settings.DEFAULT_AUTO_FIELD == "django.db.models.BigAutoField"


def test_email_uses_mailers_not_deprecated_settings():
    # Read the module itself: pytest-django swaps the live setting for an in-memory one.
    from scms import settings as project_settings

    assert project_settings.MAILERS["default"]["BACKEND"].endswith("console.EmailBackend")

    for name in ("EMAIL_BACKEND", "EMAIL_HOST", "EMAIL_PORT", "EMAIL_USE_TLS"):
        assert not hasattr(project_settings, name)
