from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

from scms.settings import database_config


def test_sqlite_defaults_and_path_override(tmp_path):
    root = Path("/example")
    expected = {
        "ENGINE": "django.db.backends.sqlite3", "NAME": root / "db.sqlite3",
        "OPTIONS": {"transaction_mode": "IMMEDIATE", "timeout": 20},
        "TEST": {"NAME": root / "test_db.sqlite3"},
    }
    assert database_config({}, root) == expected
    custom_path = tmp_path / "custom.db"
    assert database_config({"DJANGO_DB_ENGINE": "sqlite", "DJANGO_DB_PATH": str(custom_path)}, root) == {
        **expected, "NAME": str(custom_path),
    }


def test_postgresql_environment():
    env = {"DJANGO_DB_ENGINE": "postgresql", "DJANGO_DB_NAME": "testname",
           "DJANGO_DB_USER": "testuser", "DJANGO_DB_PASSWORD": "example-password",
           "DJANGO_DB_HOST": "database", "DJANGO_DB_PORT": "5433"}
    assert database_config(env, Path("/example")) == {
        "ENGINE": "django.db.backends.postgresql", "NAME": "testname", "USER": "testuser",
        "PASSWORD": "example-password", "HOST": "database", "PORT": "5433",
    }
    del env["DJANGO_DB_PORT"]
    assert database_config(env, Path("/example"))["PORT"] == "5432"


@pytest.mark.parametrize("password", [None, ""])
def test_postgresql_requires_password(password):
    env = {"DJANGO_DB_ENGINE": "postgresql"}
    if password is not None:
        env["DJANGO_DB_PASSWORD"] = password
    with pytest.raises(ImproperlyConfigured, match="DJANGO_DB_PASSWORD"):
        database_config(env, Path("/example"))


def test_unknown_database_engine():
    with pytest.raises(ImproperlyConfigured, match="Unknown DJANGO_DB_ENGINE"):
        database_config({"DJANGO_DB_ENGINE": "other"}, Path("/example"))


@pytest.mark.parametrize('age',[0,60,300])
def test_explicit_postgresql_connection_age_is_bounded_and_health_checked(age):
    result=database_config({'DJANGO_DB_ENGINE':'postgresql','DJANGO_DB_PASSWORD':'synthetic-only','DJANGO_DB_CONN_MAX_AGE':str(age)},Path('/example'))
    assert result['CONN_MAX_AGE']==age
    assert result['CONN_HEALTH_CHECKS'] is (age>0)


@pytest.mark.parametrize('age',['','-1','301','not-a-number','1.5'])
def test_invalid_connection_age_refuses_startup(age):
    with pytest.raises(ImproperlyConfigured,match='DJANGO_DB_CONN_MAX_AGE'):
        database_config({'DJANGO_DB_ENGINE':'postgresql','DJANGO_DB_PASSWORD':'synthetic-only','DJANGO_DB_CONN_MAX_AGE':age},Path('/example'))
