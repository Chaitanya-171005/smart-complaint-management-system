"""A synthetic loopback SMTP relay verifies the real Django transport boundary."""

import socketserver
from email import policy
from email.parser import BytesParser
from threading import Thread

import pytest

from workflow.email_delivery import deliver_email
from workflow.history_service import record_history
from workflow.models import EmailDelivery, Notification
from django.utils import timezone


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("temporary_failures", [0, 1, 2, 3])
def test_anonymous_smtp_delivery_retries_and_failure(complaint_factory, user_factory, settings, temporary_failures):
    envelopes, messages, attempted = [], [], []

    class Relay(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(5)
            self.wfile.write(b"220 synthetic.local ESMTP\r\n")
            while line := self.rfile.readline():
                command = line.split(b" ", 1)[0].strip().upper()
                if command in (b"EHLO", b"HELO"):
                    self.wfile.write(b"250 synthetic.local\r\n")
                elif command == b"RCPT":
                    envelopes.append(line.decode("ascii").strip())
                    self.wfile.write(b"250 OK\r\n")
                elif command == b"DATA":
                    self.wfile.write(b"354 Send message\r\n")
                    data = []
                    while (part := self.rfile.readline()) != b".\r\n":
                        if not part:
                            return
                        data.append(part)
                    attempted.append(b"".join(data))
                    if len(attempted) <= temporary_failures:
                        self.wfile.write(b"451 Synthetic temporary refusal SECRET\r\n")
                    else:
                        messages.append(b"".join(data))
                        self.wfile.write(b"250 Accepted\r\n")
                elif command == b"QUIT":
                    self.wfile.write(b"221 Bye\r\n")
                    return
                else:
                    self.wfile.write(b"250 OK\r\n")

    complaint = complaint_factory(anonymous=True)
    head = user_factory(role="HEAD", department=complaint.department)
    record_history(complaint.complaint_id, "ESCALATED", "SYSTEM", remarks="SECRET-SESSION")
    notice = Notification.objects.get(recipient=head)
    with socketserver.TCPServer(("127.0.0.1", 0), Relay) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            settings.MAILERS = {"default": {"BACKEND": "django.core.mail.backends.smtp.EmailBackend",
                                           "OPTIONS": {"host": "127.0.0.1", "port": server.server_address[1],
                                                       "timeout": 5}}}
            now = timezone.now()
            for number in range(1, min(temporary_failures + 1, 3) + 1):
                expected = "RETRY_WAIT" if number <= temporary_failures and number < 3 else (
                    "FAILED" if temporary_failures == 3 else "SENT")
                assert deliver_email(notice.email_delivery.pk, now=now) == expected
                job = EmailDelivery.objects.get(pk=notice.email_delivery.pk)
                now = job.next_attempt_at or now
        finally:
            server.shutdown()
            thread.join(timeout=5)
    assert len(messages) == (0 if temporary_failures == 3 else 1)
    assert len(envelopes) == len(attempted) == min(temporary_failures + 1, 3)
    assert all(head.email in recipient for recipient in envelopes)
    message = BytesParser(policy=policy.default).parsebytes(attempted[-1])
    assert str(message["To"]) == head.email
    assert not message["Cc"] and not message["Bcc"]
    assert complaint.complaint_id in message.get_content() and "Anonymous" in message.get_content()
    assert "SECRET-SESSION" not in attempted[-1].decode() and complaint.reference_digest not in attempted[-1].decode()
    job = EmailDelivery.objects.get(pk=notice.email_delivery.pk)
    assert job.status == ("FAILED" if temporary_failures == 3 else "SENT")
    assert job.attempt_count == len(attempted)
    assert Notification.objects.filter(pk=notice.pk).exists()
