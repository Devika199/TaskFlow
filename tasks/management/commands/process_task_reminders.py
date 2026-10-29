import sys
from datetime import date
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from organizations.models import Organization
from tasks.reminders import process_task_reminders_batch


class Command(BaseCommand):
    help = "Processes upcoming and overdue task reminders with persistent idempotency and duplicate prevention."

    def add_arguments(self, parser):
        parser.add_argument(
            '--organization',
            '-o',
            type=str,
            default='',
            help="Limit reminder processing to a specific organization (slug or ID).",
        )
        parser.add_argument(
            '--days-ahead',
            type=int,
            default=1,
            help="Number of days ahead to look for due soon tasks (default: 1).",
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help="Maximum number of tasks to process per batch (default: 100).",
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help="Simulate reminder scanning without creating notifications or log records.",
        )
        parser.add_argument(
            '--details',
            action='store_true',
            help="Print detailed output for each evaluated task.",
        )

    def handle(self, *args, **options):
        org_filter = options.get('organization', '').strip()
        days_ahead = options.get('days_ahead', 1)
        batch_size = options.get('batch_size', 100)
        dry_run = options.get('dry_run', False)
        verbose = options.get('details', False) or options.get('verbosity', 1) > 1

        org = None
        if org_filter:
            if org_filter.isdigit():
                org = Organization.objects.filter(id=int(org_filter)).first()
            else:
                org = Organization.objects.filter(slug=org_filter).first()
            if not org:
                raise CommandError(f"Organization '{org_filter}' not found.")

        today = timezone.localdate()
        mode_str = "DRY RUN (Simulated - no changes will be made)" if dry_run else "LIVE EXECUTION"
        org_str = f"{org.name} [{org.slug}]" if org else "All Organizations"

        self.stdout.write(self.style.MIGRATE_HEADING("=== TaskFlow Automated Reminder Processor ==="))
        self.stdout.write(f"Mode:            {mode_str}")
        self.stdout.write(f"Reference Date:  {today.isoformat()} (Local Timezone)")
        self.stdout.write(f"Organization:    {org_str}")
        self.stdout.write(f"Due Soon Window: {days_ahead} day(s) ahead")
        self.stdout.write(f"Batch Limit:     {batch_size} tasks")
        self.stdout.write("-" * 50)

        summary = process_task_reminders_batch(
            organization=org,
            days_ahead=days_ahead,
            batch_size=batch_size,
            dry_run=dry_run,
            reference_date=today,
        )

        if verbose and summary['details']:
            self.stdout.write("\nItem Details:")
            for item in summary['details']:
                st = item.get('status')
                tid = item.get('task_id')
                rtype = item.get('reminder_type', '')
                rec = item.get('recipient', '')
                reason = item.get('reason') or item.get('error') or ''
                detail_line = f"  - Task #{tid} [{rtype}] -> {st} (User: @{rec}) {reason}".strip()
                if st in ('SENT', 'WOULD_SEND'):
                    self.stdout.write(self.style.SUCCESS(detail_line))
                elif st == 'ALREADY_SENT':
                    self.stdout.write(self.style.WARNING(detail_line))
                elif st == 'FAILED':
                    self.stdout.write(self.style.ERROR(detail_line))
                else:
                    self.stdout.write(detail_line)

        self.stdout.write("\n" + self.style.MIGRATE_HEADING("Execution Summary:"))
        self.stdout.write(f"  Total Evaluated: {summary['processed']}")
        if dry_run:
            self.stdout.write(f"  Would Send:      {summary['would_send']}")
        else:
            self.stdout.write(f"  Reminders Sent:  {summary['sent']}")
        self.stdout.write(f"  Already Sent:    {summary['already_sent']}")
        self.stdout.write(f"  Skipped:         {summary['skipped']}")
        if summary['failed'] > 0:
            self.stdout.write(self.style.ERROR(f"  Failed:          {summary['failed']}"))
        else:
            self.stdout.write(f"  Failed:          {summary['failed']}")

        if dry_run:
            self.stdout.write(self.style.SUCCESS("\nDry run completed successfully. No records were modified."))
        else:
            self.stdout.write(self.style.SUCCESS("\nReminder processing completed successfully."))
