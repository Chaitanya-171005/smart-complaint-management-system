from django.core.management.base import BaseCommand, CommandError

from workflow.email_delivery import deliver_email, due_delivery_ids


class Command(BaseCommand):
    help = "Process due notification attempts and expired claims (three total attempts maximum)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        if options["limit"] < 1:
            raise CommandError("Limit must be positive.")
        try:
            ids = due_delivery_ids(limit=options["limit"])
        except Exception:
            raise CommandError("Notification schedules could not be read.") from None
        failures = 0
        for pk in ids:
            try:
                deliver_email(pk)
            except Exception:
                # A DB finalization failure leaves the durable claim recoverable.
                # Never print exception values, transport settings or addresses.
                failures += 1
        self.stdout.write(f"Processed {len(ids)} due deliveries.")
        if failures:
            raise CommandError("Some delivery outcomes could not be persisted; rerun the worker.")
