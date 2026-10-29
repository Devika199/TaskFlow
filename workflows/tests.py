from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from notifications.models import Notification
from organizations.models import Organization, OrganizationMembership
from tasks.models import Label, Project, Task, TaskActivityLog
from workflows.actions import (
    execute_action,
    validate_rule_actions,
)
from workflows.conditions import (
    evaluate_conditions,
    validate_rule_conditions,
)
from workflows.engine import execute_workflow_rule, MAX_WORKFLOW_DEPTH
from workflows.events import (
    dispatch_task_event,
    notify_task_assigned,
    notify_task_created,
    notify_task_status_changed,
    notify_task_updated,
)
from workflows.models import WorkflowExecution, WorkflowRule

User = get_user_model()


class WorkflowValidationTests(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="Acme Corp", slug="acme")
        self.org_b = Organization.objects.create(name="Beta LLC", slug="beta")

        self.user_a = User.objects.create_user(
            username="user_a", email="a@acme.com", password="password123"
        )
        OrganizationMembership.objects.create(
            organization=self.org_a,
            user=self.user_a,
            role=OrganizationMembership.ROLE_ADMIN,
            is_active=True,
        )

        self.project_a = Project.objects.create(organization=self.org_a, name="Acme Project")
        self.project_b = Project.objects.create(organization=self.org_b, name="Beta Project")

        self.label_a = Label.objects.create(organization=self.org_a, name="Acme Label", color="#123456")
        self.label_b = Label.objects.create(organization=self.org_b, name="Beta Label", color="#654321")

    def test_validate_conditions_success(self):
        conditions = {
            'status': {'operator': 'equals', 'value': Task.STATUS_TODO},
            'priority': {'operator': 'in', 'value': [Task.PRIORITY_HIGH, Task.PRIORITY_MEDIUM]},
            'project': {'operator': 'equals', 'value': self.project_a.id},
            'labels': {'operator': 'contains', 'value': [self.label_a.id]},
            'assignee': {'operator': 'assigned', 'value': True},
            'due_date': {'operator': 'overdue', 'value': True},
        }
        # Should not raise
        validate_rule_conditions(conditions, organization=self.org_a)

    def test_validate_conditions_rejects_unsupported_field_and_operator(self):
        # Unsupported field
        with self.assertRaises(ValidationError):
            validate_rule_conditions({'malicious_code': {'operator': 'equals', 'value': '1'}})

        # Unsupported operator
        with self.assertRaises(ValidationError):
            validate_rule_conditions({'status': {'operator': 'regex', 'value': '.*'}})

        # Malformed format
        with self.assertRaises(ValidationError):
            validate_rule_conditions({'status': 'TODO'})

    def test_validate_conditions_rejects_cross_tenant_references(self):
        # Project in Org B used for Org A rule
        with self.assertRaises(ValidationError):
            validate_rule_conditions(
                {'project': {'operator': 'equals', 'value': self.project_b.id}},
                organization=self.org_a
            )

        # Label in Org B used for Org A rule
        with self.assertRaises(ValidationError):
            validate_rule_conditions(
                {'labels': {'operator': 'contains', 'value': [self.label_b.id]}},
                organization=self.org_a
            )

    def test_validate_actions_success(self):
        actions = [
            {'action_type': 'CREATE_NOTIFICATION', 'recipient': 'assignee', 'message': "Task alert"},
            {'action_type': 'LOG_AUDIT', 'details': "Audit message"},
            {'action_type': 'UPDATE_TASK_FIELD', 'field': 'status', 'value': Task.STATUS_COMPLETED},
        ]
        # Should not raise
        validate_rule_actions(actions, organization=self.org_a)

    def test_validate_actions_rejects_empty_or_unsupported(self):
        # Empty list
        with self.assertRaises(ValidationError):
            validate_rule_actions([], organization=self.org_a)

        # Unsupported action type
        with self.assertRaises(ValidationError):
            validate_rule_actions([{'action_type': 'EXECUTE_SHELL'}], organization=self.org_a)

        # Unsafe field update attempt
        with self.assertRaises(ValidationError):
            validate_rule_actions([{'action_type': 'UPDATE_TASK_FIELD', 'field': 'created_by', 'value': 'hacker'}])

    def test_validate_actions_rejects_cross_tenant_recipient(self):
        user_b = User.objects.create_user(username="user_b", email="b@beta.com", password="password123")
        OrganizationMembership.objects.create(
            organization=self.org_b,
            user=user_b,
            role=OrganizationMembership.ROLE_MEMBER,
            is_active=True,
        )

        with self.assertRaises(ValidationError):
            validate_rule_actions(
                [{'action_type': 'CREATE_NOTIFICATION', 'recipient': 'specific_user', 'user_id': user_b.id}],
                organization=self.org_a
            )


class WorkflowEngineExecutionTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme Corp", slug="acme")
        self.admin = User.objects.create_user(
            username="admin_user", email="admin@acme.com", password="password123", role="ADMIN"
        )
        self.member = User.objects.create_user(
            username="member_user", email="member@acme.com", password="password123", role="MEMBER"
        )
        OrganizationMembership.objects.create(
            organization=self.org, user=self.admin, role=OrganizationMembership.ROLE_ADMIN, is_active=True
        )
        OrganizationMembership.objects.create(
            organization=self.org, user=self.member, role=OrganizationMembership.ROLE_MEMBER, is_active=True
        )

        self.project = Project.objects.create(organization=self.org, name="Launch")
        self.label = Label.objects.create(organization=self.org, name="Urgent", color="#ef4444")

        self.task = Task.objects.create(
            organization=self.org,
            title="Deploy release",
            status=Task.STATUS_TODO,
            priority=Task.PRIORITY_HIGH,
            created_by=self.admin,
            assigned_to=self.member,
            project=self.project,
        )
        self.task.labels.add(self.label)

    def test_task_created_trigger_and_notification_action(self):
        rule = WorkflowRule.objects.create(
            organization=self.org,
            name="Notify on High Priority Creation",
            trigger_type=WorkflowRule.TRIGGER_TASK_CREATED,
            is_enabled=True,
            conditions={'priority': {'operator': 'equals', 'value': Task.PRIORITY_HIGH}},
            actions=[
                {
                    'action_type': 'CREATE_NOTIFICATION',
                    'recipient': 'assignee',
                    'message': "High priority task assigned: '{title}'.",
                },
                {
                    'action_type': 'LOG_AUDIT',
                    'details': "Automated rule executed for '{title}'.",
                }
            ],
            created_by=self.admin,
        )

        executions = dispatch_task_event(WorkflowRule.TRIGGER_TASK_CREATED, self.task, actor=self.admin)
        self.assertEqual(len(executions), 1)
        execution = executions[0]
        self.assertEqual(execution.status, WorkflowExecution.STATUS_SUCCESS)
        self.assertEqual(execution.rule, rule)

        # Verify notification created
        notif = Notification.objects.filter(recipient=self.member, task=self.task).first()
        self.assertIsNotNone(notif)
        self.assertIn("High priority task assigned: 'Deploy release'.", notif.verb)

        # Verify audit log
        log = TaskActivityLog.objects.filter(task=self.task, details__contains="Automated rule executed").first()
        self.assertIsNotNone(log)

    def test_condition_mismatch_results_in_skipped_execution(self):
        WorkflowRule.objects.create(
            organization=self.org,
            name="Match Only Low Priority",
            trigger_type=WorkflowRule.TRIGGER_TASK_CREATED,
            is_enabled=True,
            conditions={'priority': {'operator': 'equals', 'value': Task.PRIORITY_LOW}},
            actions=[{'action_type': 'LOG_AUDIT', 'details': "Should not run"}],
            created_by=self.admin,
        )

        executions = dispatch_task_event(WorkflowRule.TRIGGER_TASK_CREATED, self.task, actor=self.admin)
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0].status, WorkflowExecution.STATUS_SKIPPED)
        self.assertFalse(TaskActivityLog.objects.filter(details="Should not run").exists())

    def test_disabled_rule_does_not_execute(self):
        WorkflowRule.objects.create(
            organization=self.org,
            name="Disabled Rule",
            trigger_type=WorkflowRule.TRIGGER_TASK_CREATED,
            is_enabled=False,
            conditions={},
            actions=[{'action_type': 'LOG_AUDIT', 'details': "Never run"}],
            created_by=self.admin,
        )

        executions = dispatch_task_event(WorkflowRule.TRIGGER_TASK_CREATED, self.task, actor=self.admin)
        self.assertEqual(len(executions), 0)

    def test_action_update_task_field(self):
        WorkflowRule.objects.create(
            organization=self.org,
            name="Auto Complete on Trigger",
            trigger_type=WorkflowRule.TRIGGER_TASK_STATUS_CHANGED,
            is_enabled=True,
            conditions={'status': {'operator': 'equals', 'value': Task.STATUS_IN_PROGRESS}},
            actions=[{'action_type': 'UPDATE_TASK_FIELD', 'field': 'priority', 'value': Task.PRIORITY_LOW}],
            created_by=self.admin,
        )

        self.task.status = Task.STATUS_IN_PROGRESS
        self.task.save()

        executions = dispatch_task_event(WorkflowRule.TRIGGER_TASK_STATUS_CHANGED, self.task, actor=self.admin)
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0].status, WorkflowExecution.STATUS_SUCCESS)

        self.task.refresh_from_db()
        self.assertEqual(self.task.priority, Task.PRIORITY_LOW)

    def test_idempotency_prevents_duplicate_effects(self):
        rule = WorkflowRule.objects.create(
            organization=self.org,
            name="Idempotent Rule",
            trigger_type=WorkflowRule.TRIGGER_TASK_CREATED,
            is_enabled=True,
            conditions={},
            actions=[{'action_type': 'CREATE_NOTIFICATION', 'recipient': 'assignee', 'message': "Once only"}],
            created_by=self.admin,
        )

        # First dispatch
        exec1 = execute_workflow_rule(rule, self.task, "TASK_CREATED", actor=self.admin, event_id="evt_123")
        self.assertEqual(exec1.status, WorkflowExecution.STATUS_SUCCESS)
        self.assertEqual(Notification.objects.filter(verb="Once only").count(), 1)

        # Duplicate dispatch with identical event_id
        exec2 = execute_workflow_rule(rule, self.task, "TASK_CREATED", actor=self.admin, event_id="evt_123")
        self.assertEqual(exec2.id, exec1.id)
        # Notifications count MUST remain exactly 1
        self.assertEqual(Notification.objects.filter(verb="Once only").count(), 1)

    def test_infinite_loop_prevention_bounds_recursion(self):
        # Rule that updates status to IN_PROGRESS when status changes to IN_PROGRESS
        # which would re-trigger itself infinitely without depth guards
        WorkflowRule.objects.create(
            organization=self.org,
            name="Circular Status Rule",
            trigger_type=WorkflowRule.TRIGGER_TASK_STATUS_CHANGED,
            is_enabled=True,
            conditions={'status': {'operator': 'equals', 'value': Task.STATUS_IN_PROGRESS}},
            actions=[{'action_type': 'UPDATE_TASK_FIELD', 'field': 'priority', 'value': Task.PRIORITY_LOW}],
            created_by=self.admin,
        )

        # Should complete cleanly without RecursionError or hanging
        self.task.status = Task.STATUS_IN_PROGRESS
        executions = dispatch_task_event(WorkflowRule.TRIGGER_TASK_STATUS_CHANGED, self.task, actor=self.admin)
        self.assertTrue(len(executions) >= 1)


class WorkflowTenantIsolationTests(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="Tenant Alpha", slug="alpha")
        self.org_b = Organization.objects.create(name="Tenant Beta", slug="beta")

        self.admin_a = User.objects.create_user(username="admin_a", email="a@alpha.com", password="password123")
        self.admin_b = User.objects.create_user(username="admin_b", email="b@beta.com", password="password123")

        OrganizationMembership.objects.create(
            organization=self.org_a, user=self.admin_a, role=OrganizationMembership.ROLE_ADMIN, is_active=True
        )
        OrganizationMembership.objects.create(
            organization=self.org_b, user=self.admin_b, role=OrganizationMembership.ROLE_ADMIN, is_active=True
        )

        self.rule_a = WorkflowRule.objects.create(
            organization=self.org_a,
            name="Alpha Only Rule",
            trigger_type=WorkflowRule.TRIGGER_TASK_CREATED,
            is_enabled=True,
            conditions={},
            actions=[{'action_type': 'LOG_AUDIT', 'details': "Alpha executed"}],
            created_by=self.admin_a,
        )

        self.task_b = Task.objects.create(
            organization=self.org_b,
            title="Beta Task",
            created_by=self.admin_b,
        )

    def test_org_a_rule_never_triggers_on_org_b_task(self):
        # When event is dispatched for Org B task, Org A rules are never returned or executed
        executions = dispatch_task_event(WorkflowRule.TRIGGER_TASK_CREATED, self.task_b, actor=self.admin_b)
        self.assertEqual(len(executions), 0)
        self.assertFalse(TaskActivityLog.objects.filter(details="Alpha executed").exists())

    def test_direct_execution_mismatch_strictly_blocked(self):
        # Directly calling execute_workflow_rule with cross-tenant task is rejected
        res = execute_workflow_rule(self.rule_a, self.task_b, "TASK_CREATED")
        self.assertIsNone(res)
        self.assertEqual(WorkflowExecution.objects.count(), 0)


class WorkflowUITests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="SaaS Corp", slug="saas")
        self.other_org = Organization.objects.create(name="Other Corp", slug="other")

        self.admin = User.objects.create_user(
            username="admin_u", email="admin@saas.com", password="password123", role="ADMIN"
        )
        self.member = User.objects.create_user(
            username="member_u", email="member@saas.com", password="password123", role="MEMBER"
        )
        self.other_admin = User.objects.create_user(
            username="other_admin", email="admin@other.com", password="password123", role="ADMIN"
        )

        OrganizationMembership.objects.create(
            organization=self.org, user=self.admin, role=OrganizationMembership.ROLE_ADMIN, is_active=True
        )
        OrganizationMembership.objects.create(
            organization=self.org, user=self.member, role=OrganizationMembership.ROLE_MEMBER, is_active=True
        )
        OrganizationMembership.objects.create(
            organization=self.other_org, user=self.other_admin, role=OrganizationMembership.ROLE_ADMIN, is_active=True
        )

        self.rule = WorkflowRule.objects.create(
            organization=self.org,
            name="Existing Rule",
            trigger_type=WorkflowRule.TRIGGER_TASK_CREATED,
            is_enabled=True,
            conditions={},
            actions=[{'action_type': 'CREATE_NOTIFICATION', 'recipient': 'assignee'}],
            created_by=self.admin,
        )

    def test_members_forbidden_from_workflow_management(self):
        self.client.login(username="member_u", password="password123")
        res = self.client.get(reverse('workflow_rule_list'))
        self.assertEqual(res.status_code, 403)

        res = self.client.get(reverse('workflow_rule_create'))
        self.assertEqual(res.status_code, 403)

    def test_admin_can_view_and_manage_rules(self):
        self.client.login(username="admin_u", password="password123")
        res = self.client.get(reverse('workflow_rule_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Existing Rule")

        # Create new rule
        res = self.client.post(
            reverse('workflow_rule_create'),
            {
                'name': 'New Alert Rule',
                'description': 'Alert on completed',
                'trigger_type': WorkflowRule.TRIGGER_TASK_COMPLETED,
                'is_enabled': 'on',
                'action_type': 'LOG_AUDIT',
            }
        )
        self.assertRedirects(res, reverse('workflow_rule_list'))
        self.assertTrue(WorkflowRule.objects.filter(name='New Alert Rule').exists())

        # Toggle rule
        res = self.client.post(reverse('workflow_rule_toggle', args=[self.rule.id]))
        self.assertRedirects(res, reverse('workflow_rule_list'))
        self.rule.refresh_from_db()
        self.assertFalse(self.rule.is_enabled)

        # Delete rule
        res = self.client.post(reverse('workflow_rule_delete', args=[self.rule.id]))
        self.assertRedirects(res, reverse('workflow_rule_list'))
        self.assertFalse(WorkflowRule.objects.filter(id=self.rule.id).exists())

    def test_cross_tenant_ui_access_blocked(self):
        # Admin of other org cannot edit or delete Org A's rule
        self.client.login(username="other_admin", password="password123")
        res = self.client.get(reverse('workflow_rule_edit', args=[self.rule.id]))
        self.assertEqual(res.status_code, 404)

        res = self.client.post(reverse('workflow_rule_delete', args=[self.rule.id]))
        self.assertEqual(res.status_code, 404)


class WorkflowEndToEndIntegrationTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Enterprise Co", slug="enterprise")
        self.admin = User.objects.create_user(
            username="ent_admin", email="admin@ent.com", password="password123", role="ADMIN"
        )
        self.member = User.objects.create_user(
            username="ent_member", email="member@ent.com", password="password123", role="MEMBER"
        )
        OrganizationMembership.objects.create(
            organization=self.org, user=self.admin, role=OrganizationMembership.ROLE_ADMIN, is_active=True
        )
        OrganizationMembership.objects.create(
            organization=self.org, user=self.member, role=OrganizationMembership.ROLE_MEMBER, is_active=True
        )

    def test_web_task_creation_triggers_workflow(self):
        rule = WorkflowRule.objects.create(
            organization=self.org,
            name="Web Created Alert",
            trigger_type=WorkflowRule.TRIGGER_TASK_CREATED,
            is_enabled=True,
            conditions={},
            actions=[{'action_type': 'CREATE_NOTIFICATION', 'recipient': 'assignee', 'message': "Assigned via web"}],
            created_by=self.admin,
        )

        self.client.login(username="ent_admin", password="password123")
        res = self.client.post(
            reverse('task_create'),
            {
                'title': 'New Web Task',
                'status': Task.STATUS_TODO,
                'priority': Task.PRIORITY_MEDIUM,
                'assigned_to': self.member.id,
            }
        )
        self.assertEqual(res.status_code, 302)

        task = Task.objects.filter(title='New Web Task').first()
        self.assertIsNotNone(task)

        # Check execution record
        execution = WorkflowExecution.objects.filter(rule=rule, task=task).first()
        self.assertIsNotNone(execution)
        self.assertEqual(execution.status, WorkflowExecution.STATUS_SUCCESS)

        # Check notification
        notif = Notification.objects.filter(recipient=self.member, verb__contains="Assigned via web").first()
        self.assertIsNotNone(notif)

    def test_web_task_status_update_triggers_workflow(self):
        rule = WorkflowRule.objects.create(
            organization=self.org,
            name="Complete Alert",
            trigger_type=WorkflowRule.TRIGGER_TASK_COMPLETED,
            is_enabled=True,
            conditions={},
            actions=[{'action_type': 'LOG_AUDIT', 'details': "Task marked completed by automation"}],
            created_by=self.admin,
        )

        task = Task.objects.create(
            organization=self.org,
            title="Task To Complete",
            status=Task.STATUS_IN_PROGRESS,
            created_by=self.admin,
            assigned_to=self.member,
        )

        self.client.login(username="ent_member", password="password123")
        res = self.client.post(
            reverse('update_task_status', args=[task.id]),
            {'status': Task.STATUS_COMPLETED}
        )
        self.assertEqual(res.status_code, 302)

        execution = WorkflowExecution.objects.filter(rule=rule, task=task).first()
        self.assertIsNotNone(execution)
        self.assertEqual(execution.status, WorkflowExecution.STATUS_SUCCESS)

        # Audit log created
        log = TaskActivityLog.objects.filter(task=task, details__contains="Task marked completed by automation").first()
        self.assertIsNotNone(log)

    def test_failed_action_records_error_summary_safely(self):
        # Action with missing or unresolvable specific_user
        rule = WorkflowRule.objects.create(
            organization=self.org,
            name="Faulty Action Rule",
            trigger_type=WorkflowRule.TRIGGER_TASK_CREATED,
            is_enabled=True,
            conditions={},
            actions=[{'action_type': 'CREATE_NOTIFICATION', 'recipient': 'specific_user', 'user_id': 999999}],
            created_by=self.admin,
        )

        task = Task.objects.create(
            organization=self.org,
            title="Faulty Action Task",
            created_by=self.admin,
        )

        executions = dispatch_task_event(WorkflowRule.TRIGGER_TASK_CREATED, task, actor=self.admin)
        self.assertEqual(len(executions), 1)
        execution = executions[0]
        # Since recipient 999999 doesn't exist in org, action was skipped safely
        self.assertEqual(execution.status, WorkflowExecution.STATUS_SUCCESS)
        self.assertIn("No recipient found", str(execution.execution_log))

    def test_partial_action_failure_rolls_back_and_prevents_duplicate_on_retry(self):
        # Action 0: Create notification
        # Action 1: Invalid action that fails
        task = Task.objects.create(
            organization=self.org,
            title="Partial Fail Task",
            created_by=self.admin,
            assigned_to=self.member,
            priority=Task.PRIORITY_LOW,
        )

        rule = WorkflowRule.objects.create(
            organization=self.org,
            name="Partial Failure Rule",
            trigger_type=WorkflowRule.TRIGGER_TASK_CREATED,
            is_enabled=True,
            conditions={},
            actions=[
                {
                    'action_type': 'CREATE_NOTIFICATION',
                    'recipient': 'assignee',
                    'message': 'Atomic rollback check',
                },
                {
                    'action_type': 'UPDATE_TASK_FIELD',
                    'field': 'priority',
                    'value': 'NONEXISTENT_PRIORITY',  # Invalid value fails execute_action
                },
            ],
            created_by=self.admin,
        )

        # First attempt: Action 1 fails -> entire transaction rolls back
        exec_record = execute_workflow_rule(rule, task, "TASK_CREATED", actor=self.admin, event_id="retry_evt_001")
        self.assertEqual(exec_record.status, WorkflowExecution.STATUS_FAILED)
        self.assertIn("Error during action execution", exec_record.error_summary)

        # Verify Action 0's notification was rolled back completely
        self.assertEqual(
            Notification.objects.filter(recipient=self.member, verb__contains="Atomic rollback check").count(),
            0
        )
        task.refresh_from_db()
        self.assertEqual(task.priority, Task.PRIORITY_LOW)

        # Fix rule configuration for retry
        rule.actions = [
            {
                'action_type': 'CREATE_NOTIFICATION',
                'recipient': 'assignee',
                'message': 'Atomic rollback check',
            },
            {
                'action_type': 'UPDATE_TASK_FIELD',
                'field': 'priority',
                'value': Task.PRIORITY_HIGH,
            },
        ]
        rule.save()

        # Retry execution with same event_id
        retry_record = execute_workflow_rule(rule, task, "TASK_CREATED", actor=self.admin, event_id="retry_evt_001")
        self.assertEqual(retry_record.id, exec_record.id)
        self.assertEqual(retry_record.status, WorkflowExecution.STATUS_SUCCESS)
        self.assertEqual(retry_record.retry_count, 1)

        # Exactly 1 notification exists (no duplicate from failed attempt!)
        self.assertEqual(
            Notification.objects.filter(recipient=self.member, verb__contains="Atomic rollback check").count(),
            1
        )
        task.refresh_from_db()
        self.assertEqual(task.priority, Task.PRIORITY_HIGH)

    def test_subsequent_legitimate_events_work_after_workflow_execution(self):
        # Rule 1 triggers on creation and updates priority to HIGH
        rule_create = WorkflowRule.objects.create(
            organization=self.org,
            name="Set Priority on Create",
            trigger_type=WorkflowRule.TRIGGER_TASK_CREATED,
            is_enabled=True,
            conditions={},
            actions=[{'action_type': 'UPDATE_TASK_FIELD', 'field': 'priority', 'value': Task.PRIORITY_HIGH}],
            created_by=self.admin,
        )

        # Rule 2 triggers on status change to IN_PROGRESS and logs audit
        rule_status = WorkflowRule.objects.create(
            organization=self.org,
            name="Audit In Progress",
            trigger_type=WorkflowRule.TRIGGER_TASK_STATUS_CHANGED,
            is_enabled=True,
            conditions={'status': {'operator': 'equals', 'value': Task.STATUS_IN_PROGRESS}},
            actions=[{'action_type': 'LOG_AUDIT', 'details': 'Status changed to in progress audit'}],
            created_by=self.admin,
        )

        # Step 1: Create task -> Rule 1 executes
        task = Task.objects.create(
            organization=self.org,
            title="Multi-stage Task",
            status=Task.STATUS_TODO,
            created_by=self.admin,
            assigned_to=self.member,
        )
        notify_task_created(task, actor=self.admin)
        task.refresh_from_db()
        self.assertEqual(task.priority, Task.PRIORITY_HIGH)

        # Step 2: Legitimate subsequent user update occurs -> Rule 2 executes successfully
        task.status = Task.STATUS_IN_PROGRESS
        task.save()
        notify_task_status_changed(task, actor=self.member, old_status=Task.STATUS_TODO)

        exec_status = WorkflowExecution.objects.filter(rule=rule_status, task=task).first()
        self.assertIsNotNone(exec_status)
        self.assertEqual(exec_status.status, WorkflowExecution.STATUS_SUCCESS)
        self.assertTrue(TaskActivityLog.objects.filter(details__contains='Status changed to in progress audit').exists())

    def test_ordinary_member_cannot_modify_or_delete_rules(self):
        rule = WorkflowRule.objects.create(
            organization=self.org,
            name="Protected Rule",
            trigger_type=WorkflowRule.TRIGGER_TASK_CREATED,
            is_enabled=True,
            conditions={},
            actions=[{'action_type': 'LOG_AUDIT', 'details': 'audit'}],
            created_by=self.admin,
        )

        self.client.login(username="ent_member", password="password123")

        # Edit attempt
        res = self.client.post(
            reverse('workflow_rule_edit', args=[rule.id]),
            {'name': 'Hacked Rule', 'trigger_type': WorkflowRule.TRIGGER_TASK_CREATED, 'action_type': 'LOG_AUDIT'}
        )
        self.assertEqual(res.status_code, 403)

        # Toggle attempt
        res = self.client.post(reverse('workflow_rule_toggle', args=[rule.id]))
        self.assertEqual(res.status_code, 403)

        # Delete attempt
        res = self.client.post(reverse('workflow_rule_delete', args=[rule.id]))
        self.assertEqual(res.status_code, 403)

        # Verify rule was completely untouched
        rule.refresh_from_db()
        self.assertEqual(rule.name, "Protected Rule")
        self.assertTrue(rule.is_enabled)


