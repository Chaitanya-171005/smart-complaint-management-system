from django.core.management.base import BaseCommand, CommandError

from routing.escalation import run_escalation
from routing.models import EscalationRun


class Command(BaseCommand):
    help = "Run the scheduled overdue complaint escalation pass."

    def handle(self, *args, **options):
        try:
            run = run_escalation()
        except Exception as exc:
            run = getattr(exc, "escalation_run", None)
            if run is None:
                raise CommandError("Escalation run could not start.") from exc
            self.stdout.write(
                f"run={run.pk} status={run.status} examined={run.examined} "
                f"escalated={run.escalated} skipped={run.skipped} failed={run.failed}"
            )
            raise CommandError("Escalation run failed.") from exc
        self.stdout.write(
            f"run={run.pk} status={run.status} examined={run.examined} "
            f"escalated={run.escalated} skipped={run.skipped} failed={run.failed}"
        )
        if run.status == EscalationRun.Status.FAILED:
            raise CommandError("Escalation run failed.")
