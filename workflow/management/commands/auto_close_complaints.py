from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.management.base import BaseCommand, CommandError

from workflow.autoclose import run_auto_close


class Command(BaseCommand):
    help = 'Close expired unconfirmed resolutions under proposed D05 policy.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        try:
            count = run_auto_close(limit=options['limit'])
        except (ImproperlyConfigured, ValidationError):
            raise CommandError('Invalid auto-close configuration or batch limit.') from None
        except Exception:
            raise CommandError('Auto-close batch interrupted; completed actions remain durable. Rerun safely.') from None
        self.stdout.write(f'Automatically closed {count} complaints.')
