from datetime import date, timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone
import io

from notifications.models import Notification
from organizations.models import Organization, OrganizationMembership
from tasks.models import Task, TaskActivityLog, TaskReminderLog
from tasks.reminders import (
    generate_reminder_idempotency_key,
    is_task_eligible_for_reminder,
    process_task_reminder,
    process_task_reminders_batch,
)

User = get_user_model()


class TaskReminderServiceTests(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="Acme Corp", slug="acme")
        self.org_b = Organization.objects.create(name="Beta LLC", slug="beta")

        self.user_a = User.objects.create_user(
            username="alice", email="alice@acme.test", password="password123"
        )
        self.user_b = User.objects.create_user(
            username="bob", email="bob@beta.test", password="password123"
        )
        self.inactive_user = User.objects.create_user(
            username="inactive_user", email="inactive@acme.test", password="password123", is_active=False
        )

        OrganizationMembership.objects.create(
            organization=self.org_a, user=self.user_a, role=OrganizationMembership.ROLE_MEMBER, is_active=True
        )
        OrganizationMembership.objects.create(
            organization=self.org_b, user=self.user_b, role=OrganizationMembership.ROLE_MEMBER, is_active=True
        )

        self.today = date(2026, 10, 29)

    def test_eligibility_checks(self):
        # 1. Eligible task
        task = Task.objects.create(
            organization=self.org_a,
            title="Eligible Task",
            status=Task.STATUS_TODO,
            due_date=self.today,
            assigned_to=self.user_a,
        )
        eligible, reason = is_task_eligible_for_reminder(task)
        self.assertTrue(eligible)
        self.assertEqual(reason, "Eligible")

        # 2. Completed task -> Ineligible
        task.status = Task.STATUS_COMPLETED
        eligible, reason = is_task_eligible_for_reminder(task)
        self.assertFalse(eligible)
        self.assertEqual(reason, "Task is completed")

        # 3. Task without due date -> Ineligible
        task.status = Task.STATUS_TODO
        task.due_date = None
        eligible, reason = is_task_eligible_for_reminder(task)
        self.assertFalse(eligible)
        self.assertEqual(reason, "Task has no due date")

        # 4. Unassigned task -> Ineligible
        task.due_date = self.today
        task.assigned_to = None
        eligible, reason = is_task_eligible_for_reminder(task)
        self.assertFalse(eligible)
        self.assertEqual(reason, "Task has no assignee")

        # 5. Inactive user -> Ineligible
        task.assigned_to = self.inactive_user
        eligible, reason = is_task_eligible_for_reminder(task)
        self.assertFalse(eligible)
        self.assertEqual(reason, "Assignee account is inactive")

        # 6. Assignee from different organization -> Ineligible
        task.assigned_to = self.user_b
        eligible, reason = is_task_eligible_for_reminder(task)
        self.assertFalse(eligible)
        self.assertEqual(reason, "Assignee is not an active member of the task organization")

    def test_due_soon_and_overdue_reminder_processing(self):
        # Task due soon (tomorrow)
        task_soon = Task.objects.create(
            organization=self.org_a,
            title="Upcoming Task",
            status=Task.STATUS_TODO,
            due_date=self.today + timedelta(days=1),
            assigned_to=self.user_a,
        )

        res_soon = process_task_reminder(
            task_soon,
            TaskReminderLog.REMINDER_DUE_SOON,
            reference_date=self.today,
        )
        self.assertEqual(res_soon['status'], 'SENT')
        self.assertTrue(Notification.objects.filter(recipient=self.user_a, verb__contains="due soon").exists())
        self.assertTrue(TaskReminderLog.objects.filter(task=task_soon, status=TaskReminderLog.STATUS_SENT).exists())

        # Task overdue (yesterday)
        task_overdue = Task.objects.create(
            organization=self.org_a,
            title="Overdue Task",
            status=Task.STATUS_IN_PROGRESS,
            due_date=self.today - timedelta(days=2),
            assigned_to=self.user_a,
        )

        res_overdue = process_task_reminder(
            task_overdue,
            TaskReminderLog.REMINDER_OVERDUE,
            reference_date=self.today,
        )
        self.assertEqual(res_overdue['status'], 'SENT')
        self.assertTrue(Notification.objects.filter(recipient=self.user_a, verb__contains="Overdue Alert").exists())
        self.assertTrue(TaskReminderLog.objects.filter(task=task_overdue, status=TaskReminderLog.STATUS_SENT).exists())

    def test_idempotency_prevents_duplicate_reminders(self):
        task = Task.objects.create(
            organization=self.org_a,
            title="Idempotent Task",
            status=Task.STATUS_TODO,
            due_date=self.today,
            assigned_to=self.user_a,
        )

        # First run -> SENT
        res1 = process_task_reminder(task, TaskReminderLog.REMINDER_DUE_SOON, reference_date=self.today)
        self.assertEqual(res1['status'], 'SENT')
        self.assertEqual(Notification.objects.filter(recipient=self.user_a).count(), 1)
        self.assertEqual(TaskReminderLog.objects.filter(task=task).count(), 1)

        # Second run with same task and date -> ALREADY_SENT
        res2 = process_task_reminder(task, TaskReminderLog.REMINDER_DUE_SOON, reference_date=self.today)
        self.assertEqual(res2['status'], 'ALREADY_SENT')
        # Exactly 1 notification and 1 log exist
        self.assertEqual(Notification.objects.filter(recipient=self.user_a).count(), 1)
        self.assertEqual(TaskReminderLog.objects.filter(task=task).count(), 1)

    def test_database_enforced_uniqueness_constraint(self):
        task = Task.objects.create(
            organization=self.org_a,
            title="Constraint Task",
            status=Task.STATUS_TODO,
            due_date=self.today,
            assigned_to=self.user_a,
        )
        key = generate_reminder_idempotency_key(task.id, TaskReminderLog.REMINDER_DUE_SOON, self.today)
        TaskReminderLog.objects.create(
            organization=self.org_a,
            task=task,
            recipient=self.user_a,
            reminder_type=TaskReminderLog.REMINDER_DUE_SOON,
            target_due_date=self.today,
            status=TaskReminderLog.STATUS_SENT,
            idempotency_key=key,
        )

        # Duplicate tuple (task, reminder_type, target_due_date) violates unique constraint
        with self.assertRaises(IntegrityError):
            TaskReminderLog.objects.create(
                organization=self.org_a,
                task=task,
                recipient=self.user_a,
                reminder_type=TaskReminderLog.REMINDER_DUE_SOON,
                target_due_date=self.today,
                status=TaskReminderLog.STATUS_PENDING,
                idempotency_key=key + "_duplicate",
            )

    def test_rescheduled_due_date_allows_new_reminder_period(self):
        task = Task.objects.create(
            organization=self.org_a,
            title="Rescheduled Task",
            status=Task.STATUS_TODO,
            due_date=self.today,
            assigned_to=self.user_a,
        )

        # First reminder for today's due date
        res1 = process_task_reminder(task, TaskReminderLog.REMINDER_DUE_SOON, reference_date=self.today)
        self.assertEqual(res1['status'], 'SENT')
        self.assertEqual(TaskReminderLog.objects.filter(task=task).count(), 1)

        # User reschedules task due date to next month
        new_due_date = self.today + timedelta(days=30)
        task.due_date = new_due_date
        task.save(update_fields=['due_date'])

        # Reminder run for the new due date period
        new_reference_date = new_due_date - timedelta(days=1)
        res2 = process_task_reminder(task, TaskReminderLog.REMINDER_DUE_SOON, reference_date=new_reference_date)
        self.assertEqual(res2['status'], 'SENT')
        # Two distinct reminder logs exist for the two distinct due date periods
        self.assertEqual(TaskReminderLog.objects.filter(task=task).count(), 2)

    def test_failed_reminder_retry_behavior(self):
        task = Task.objects.create(
            organization=self.org_a,
            title="Faulty Task",
            status=Task.STATUS_TODO,
            due_date=self.today,
            assigned_to=self.user_a,
        )

        # Simulate exception during notification creation
        with patch('tasks.reminders.create_notification', side_effect=RuntimeError("Mailbox service unavailable")):
            res = process_task_reminder(task, TaskReminderLog.REMINDER_DUE_SOON, reference_date=self.today)
            self.assertEqual(res['status'], 'FAILED')

        log = TaskReminderLog.objects.get(task=task)
        self.assertEqual(log.status, TaskReminderLog.STATUS_FAILED)
        self.assertIn("Mailbox service unavailable", log.error_summary)
        self.assertEqual(Notification.objects.filter(recipient=self.user_a).count(), 0)

        # Retry without failure
        retry_res = process_task_reminder(task, TaskReminderLog.REMINDER_DUE_SOON, reference_date=self.today)
        self.assertEqual(retry_res['status'], 'SENT')

        log.refresh_from_db()
        self.assertEqual(log.status, TaskReminderLog.STATUS_SENT)
        self.assertIsNotNone(log.sent_at)
        self.assertEqual(Notification.objects.filter(recipient=self.user_a).count(), 1)


class TaskReminderCommandTests(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="Acme Corp", slug="acme")
        self.org_b = Organization.objects.create(name="Beta LLC", slug="beta")

        self.user_a = User.objects.create_user(
            username="alice", email="alice@acme.test", password="password123"
        )
        self.user_b = User.objects.create_user(
            username="bob", email="bob@beta.test", password="password123"
        )

        OrganizationMembership.objects.create(
            organization=self.org_a, user=self.user_a, role=OrganizationMembership.ROLE_MEMBER, is_active=True
        )
        OrganizationMembership.objects.create(
            organization=self.org_b, user=self.user_b, role=OrganizationMembership.ROLE_MEMBER, is_active=True
        )

        self.today = timezone.localdate()

        # Task in Org A (due today)
        self.task_a = Task.objects.create(
            organization=self.org_a,
            title="Org A Task",
            status=Task.STATUS_TODO,
            due_date=self.today,
            assigned_to=self.user_a,
        )

        # Task in Org B (overdue)
        self.task_b = Task.objects.create(
            organization=self.org_b,
            title="Org B Task",
            status=Task.STATUS_IN_PROGRESS,
            due_date=self.today - timedelta(days=2),
            assigned_to=self.user_b,
        )

    def test_dry_run_creates_zero_records(self):
        out = io.StringIO()
        call_command('process_task_reminders', '--dry-run', stdout=out)
        output = out.getvalue()

        self.assertIn("DRY RUN", output)
        self.assertIn("Would Send:      2", output)
        # Database must have 0 reminder logs and 0 notifications
        self.assertEqual(TaskReminderLog.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 0)

    def test_live_execution_sends_reminders(self):
        out = io.StringIO()
        call_command('process_task_reminders', stdout=out)
        output = out.getvalue()

        self.assertIn("Reminders Sent:  2", output)
        self.assertEqual(TaskReminderLog.objects.filter(status=TaskReminderLog.STATUS_SENT).count(), 2)
        self.assertEqual(Notification.objects.count(), 2)

        # Second run immediately after -> 0 sent, 2 already sent
        out2 = io.StringIO()
        call_command('process_task_reminders', stdout=out2)
        output2 = out2.getvalue()
        self.assertIn("Reminders Sent:  0", output2)
        self.assertIn("Already Sent:    2", output2)

    def test_organization_scoped_execution(self):
        # Process only Org A
        out = io.StringIO()
        call_command('process_task_reminders', '-o', 'acme', stdout=out)
        output = out.getvalue()

        self.assertIn("Organization:    Acme Corp [acme]", output)
        self.assertIn("Reminders Sent:  1", output)

        # Only Org A received reminder
        self.assertEqual(TaskReminderLog.objects.filter(organization=self.org_a).count(), 1)
        self.assertEqual(TaskReminderLog.objects.filter(organization=self.org_b).count(), 0)

    def test_single_task_failure_does_not_abort_batch(self):
        # When task A encounters an exception during processing, task B still finishes
        from tasks.reminders import process_task_reminder as original_process

        def fake_process(task, reminder_type, reference_date=None, dry_run=False):
            if task.id == self.task_a.id:
                raise RuntimeError("Simulated single task database lock")
            return original_process(task, reminder_type, reference_date=reference_date, dry_run=dry_run)

        with patch('tasks.reminders.process_task_reminder', side_effect=fake_process):
            summary = process_task_reminders_batch(reference_date=self.today)
            self.assertEqual(summary['failed'], 1)
            self.assertEqual(summary['sent'], 1)
            # Org B task still successfully dispatched
            self.assertTrue(TaskReminderLog.objects.filter(task=self.task_b, status=TaskReminderLog.STATUS_SENT).exists())
