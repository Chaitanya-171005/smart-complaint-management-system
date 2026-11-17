# SMTP deployment setup

Console output is the default, including when DEBUG is false. Production delivery
requires explicitly selecting `DJANGO_MAIL_BACKEND=smtp`; settings do not infer
deployment intent from DEBUG. Django 6.1 uses `MAILERS["default"]["OPTIONS"]`,
not the deprecated EMAIL_HOST/EMAIL_PORT settings. `DEFAULT_FROM_EMAIL` supplies
the sender when callers do not specify one. See the
[Django mail configuration reference](https://docs.djangoproject.com/en/6.1/topics/email/).

| Environment variable | Default / requirement |
| --- | --- |
| DJANGO_MAIL_BACKEND | console; only console or smtp accepted |
| DJANGO_DEFAULT_FROM_EMAIL | webmaster@localhost for console; explicit valid bare address required for SMTP |
| DJANGO_SMTP_HOST | Required SMTP hostname, without a URL scheme |
| DJANGO_SMTP_PORT | Blank/unset: 587 for STARTTLS, 465 for implicit TLS; custom ports 1–65535 supported |
| DJANGO_SMTP_USERNAME | Optional; must be paired with password |
| DJANGO_SMTP_PASSWORD | Optional; provider-issued secret, preserved verbatim |
| DJANGO_SMTP_TIMEOUT | 10 seconds; finite positive number required |
| DJANGO_SMTP_USE_TLS | True; STARTTLS, boolean True/False (case-insensitive) |
| DJANGO_SMTP_USE_SSL | False; implicit TLS, boolean True/False (case-insensitive) |

SMTP requires exactly one encryption mode. STARTTLS with port 465, implicit TLS
with port 587, malformed booleans, invalid numeric values and incomplete
credentials fail at startup without echoing secret values. Both credentials may
be empty for a provider-approved encrypted relay. No plaintext SMTP bypass or
certificate-verification bypass is provided. Django's verified SSL context and
the container/system trust store are used. For private CAs, arrange trusted CA
installation through the deployment owner; do not disable verification.

## Safe setup

1. Obtain an approved provider hostname, encrypted port, sender/domain and a
   least-privilege application credential. Configure provider sender verification
   and domain SPF/DKIM/DMARC as applicable. These are deployment dependencies.
2. Populate a private environment file from `.env.example` for local use or
   `.env.docker.example` for Docker. Restrict its permissions (`chmod 600`).
   Never commit it or put secrets in shell history, screenshots or evidence.
   Preserve any existing deployment environment file and fill only approved values.
3. Select smtp and fill host/sender. For STARTTLS use TLS=True, SSL=False,
   port 587; for implicit TLS use TLS=False, SSL=True, port 465. Supply both
   authentication values if required. Console remains available for development.
4. Compose forwards mail settings only to app, not db. Use the existing deployment
   procedure with the private env file. Plain `docker compose config` can reveal
   interpolated credentials: validate using `config --quiet`, and do not capture
   resolved secret-bearing configuration. Environment credentials are accessible
   to authorized container/host administrators; protect that access.
5. Run Django checks in an isolated deployment environment. `check --deploy`
   neither connects to SMTP nor proves deliverability. Preserve the existing
   HTTPS, CSRF, secure-cookie and verified-proxy release checks.

## Controlled delivery verification later

Only after separate authorization, use an approved synthetic recipient and
non-sensitive message, never anonymous complaint text or reference data. In the
configured app shell, the controlled operation is:

```python
from django.core.mail import send_mail
sent = send_mail("SCMS controlled delivery check", "Synthetic SMTP check.",
                 None, ["APPROVED_TEST_RECIPIENT"], using="default")
assert sent == 1
```

Replace the recipient placeholder with the approved address. Confirm provider
acceptance, receipt, expected From address, TLS negotiation and SPF/DKIM results.
Do not put credentials, raw provider exceptions or recipient details in shared
evidence. A return value of 1 means SMTP submission, not guaranteed inbox delivery.

SMTP errors propagate (`fail_silently=False`); this configuration provides no
retry/outbox service. Future F4 services must catch failures at their delivery
boundary, record sanitized outcomes, implement their own retry/idempotency and
authorize safe anonymous projections. This change sends no production mail and
does not activate the F3 notification hook or any privacy release flags.
