"""Dry-run or reconcile private evidence after interrupted storage/intake work."""

from django.core.management.base import BaseCommand, CommandError

from complaints.evidence_recovery import EvidenceRecoveryUnavailable, reconcile_evidence


class Command(BaseCommand):
    help = "Check private evidence; --apply restores accepted files and quarantines unreferenced files."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Apply the verified recovery plan.")
        parser.add_argument("--purge-quarantine", action="store_true",
                            help="With --apply, delete previously quarantined files still unreferenced.")

    def handle(self, *args, **options):
        try:
            report = reconcile_evidence(apply=options["apply"], purge_quarantine=options["purge_quarantine"])
        except EvidenceRecoveryUnavailable as error:
            raise CommandError(str(error)) from None
        except Exception:
            raise CommandError("Evidence recovery is unavailable; no successful result was recorded.") from None
        self.stdout.write(
            f"mode={'apply' if report.applied else 'dry-run'} referenced={report.referenced} "
            f"orphans={report.orphaned} quarantined_before={report.quarantined} "
            f"restore={report.restorable} purge_candidates={report.purgeable} ignored={report.ignored}"
        )
