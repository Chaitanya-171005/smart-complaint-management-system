"""Configuration and transport contracts; SMTP is always mocked."""
import smtplib
import ssl
from pathlib import Path
from unittest.mock import Mock

import pytest
from django.core import mail
from django.core.exceptions import ImproperlyConfigured

from scms.mail_config import mail_config


def smtp(**overrides):
    return {"DJANGO_MAIL_BACKEND": "smtp", "DJANGO_SMTP_HOST": "smtp.example.test",
            "DJANGO_DEFAULT_FROM_EMAIL": "scms@example.test", **overrides}


def test_development_defaults(settings, capsys):
    settings.MAILERS, settings.DEFAULT_FROM_EMAIL = mail_config({})
    assert settings.MAILERS["default"]["BACKEND"].endswith("console.EmailBackend")
    assert mail.send_mail("Synthetic", "Body", None, ["recipient@example.test"], using="default") == 1
    assert "From: webmaster@localhost" in capsys.readouterr().out


@pytest.mark.parametrize("ssl_mode,port", [(False, 587), (True, 465)])
@pytest.mark.parametrize("authenticated", [False, True])
def test_smtp_delivery_uses_verified_transport(settings, monkeypatch, ssl_mode, port, authenticated):
    env = smtp(DJANGO_SMTP_USE_TLS=str(not ssl_mode), DJANGO_SMTP_USE_SSL=str(ssl_mode))
    if authenticated:
        env.update(DJANGO_SMTP_USERNAME="synthetic-user", DJANGO_SMTP_PASSWORD="synthetic-password")
    settings.MAILERS, settings.DEFAULT_FROM_EMAIL = mail_config(env)
    connection = Mock()
    transport = Mock(return_value=connection)
    monkeypatch.setattr(smtplib, "SMTP_SSL" if ssl_mode else "SMTP", transport)
    monkeypatch.setattr("django.core.mail.backends.smtp.DNS_NAME.get_fqdn", lambda: "test.local")
    assert mail.send_mail("Synthetic", "Body", None, ["recipient@example.test"], using="default") == 1
    assert transport.call_args.args == ("smtp.example.test", port)
    assert transport.call_args.kwargs["timeout"] == 10
    context = (transport.call_args.kwargs["context"] if ssl_mode
               else connection.starttls.call_args.kwargs["context"])
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    assert connection.starttls.call_count == int(not ssl_mode)
    assert connection.login.call_count == int(authenticated)
    if authenticated:
        connection.login.assert_called_once_with("synthetic-user", "synthetic-password")
    assert connection.sendmail.call_args.args[0] == "scms@example.test"


@pytest.mark.parametrize("values", [
    {"DJANGO_MAIL_BACKEND": "typo"}, {"DJANGO_SMTP_HOST": ""},
    {"DJANGO_SMTP_HOST": "smtp://host"}, {"DJANGO_SMTP_HOST": "bad host"},
    {"DJANGO_SMTP_USE_TLS": "yes"}, {"DJANGO_SMTP_USE_SSL": "yes"},
    {"DJANGO_SMTP_USE_SSL": "True"}, {"DJANGO_SMTP_USE_TLS": "False"},
    {"DJANGO_SMTP_PORT": "465"},
    {"DJANGO_SMTP_USE_TLS": "False", "DJANGO_SMTP_USE_SSL": "True", "DJANGO_SMTP_PORT": "587"},
    {"DJANGO_SMTP_PORT": "0"}, {"DJANGO_SMTP_PORT": "65536"}, {"DJANGO_SMTP_PORT": "bad"},
    {"DJANGO_SMTP_TIMEOUT": "0"}, {"DJANGO_SMTP_TIMEOUT": "-1"},
    {"DJANGO_SMTP_TIMEOUT": "nan"}, {"DJANGO_SMTP_TIMEOUT": "inf"}, {"DJANGO_SMTP_TIMEOUT": "bad"},
    {"DJANGO_DEFAULT_FROM_EMAIL": ""}, {"DJANGO_DEFAULT_FROM_EMAIL": "bad"},
    {"DJANGO_DEFAULT_FROM_EMAIL": "user@example.test\nBcc: other@example.test"},
    {"DJANGO_SMTP_USERNAME": "synthetic-secret"}, {"DJANGO_SMTP_PASSWORD": "synthetic-secret"},
    {"DJANGO_SMTP_USERNAME": " ", "DJANGO_SMTP_PASSWORD": "synthetic-secret"},
])
def test_invalid_configuration_fails_without_echoing_values(values):
    with pytest.raises(ImproperlyConfigured) as error:
        mail_config(smtp(**values))
    assert "synthetic-secret" not in str(error.value)


def test_custom_port_timeout_and_password_preservation():
    config, _ = mail_config(smtp(DJANGO_SMTP_PORT="2525", DJANGO_SMTP_TIMEOUT="2.5",
                               DJANGO_SMTP_USERNAME="user", DJANGO_SMTP_PASSWORD=" secret "))
    options = config["default"]["OPTIONS"]
    assert (options["port"], options["timeout"], options["password"]) == (2525, 2.5, " secret ")


@pytest.mark.parametrize("stage", ["connect", "tls", "auth", "send"])
def test_delivery_failures_propagate(settings, monkeypatch, stage):
    settings.MAILERS, settings.DEFAULT_FROM_EMAIL = mail_config(smtp(
        DJANGO_SMTP_USERNAME="user", DJANGO_SMTP_PASSWORD="synthetic-password"))
    connection = Mock()
    transport = Mock(return_value=connection)
    error = smtplib.SMTPException("Synthetic delivery failure")
    if stage == "connect":
        transport.side_effect = error
    else:
        getattr(connection, {"tls": "starttls", "auth": "login", "send": "sendmail"}[stage]).side_effect = error
    monkeypatch.setattr(smtplib, "SMTP", transport)
    monkeypatch.setattr("django.core.mail.backends.smtp.DNS_NAME.get_fqdn", lambda: "test.local")
    with pytest.raises(smtplib.SMTPException, match="Synthetic delivery failure"):
        mail.send_mail("Synthetic", "Body", None, ["recipient@example.test"], using="default")


@pytest.mark.parametrize("error", [TimeoutError("Synthetic timeout"),
                                  ssl.SSLCertVerificationError("Synthetic untrusted certificate")])
def test_transport_security_and_timeout_errors_are_not_suppressed(settings, monkeypatch, error):
    settings.MAILERS, settings.DEFAULT_FROM_EMAIL = mail_config(smtp())
    transport = Mock(side_effect=error)
    monkeypatch.setattr(smtplib, "SMTP", transport)
    monkeypatch.setattr("django.core.mail.backends.smtp.DNS_NAME.get_fqdn", lambda: "test.local")
    with pytest.raises(type(error)):
        mail.send_mail("Synthetic", "Body", None, ["recipient@example.test"], using="default")


def test_compose_and_examples_forward_all_mail_variables():
    root = Path(__file__).resolve().parent.parent
    compose = (root / "docker-compose.yml").read_text()
    app = compose.split("  app:", 1)[1]
    for name in ("DJANGO_MAIL_BACKEND", "DJANGO_DEFAULT_FROM_EMAIL", "DJANGO_SMTP_HOST",
                 "DJANGO_SMTP_PORT", "DJANGO_SMTP_USERNAME", "DJANGO_SMTP_PASSWORD",
                 "DJANGO_SMTP_TIMEOUT", "DJANGO_SMTP_USE_TLS", "DJANGO_SMTP_USE_SSL"):
        assert f"{name}: ${{{name}:-" in app
        for example in (".env.example", ".env.docker.example"):
            assert f"{name}=" in (root / example).read_text()
