import os
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.server.mcpserver.exceptions import ToolError

from notifications.models import Notification
from tasks.models import Label, Project, Task, TaskActivityLog, TaskChecklistItem

from . import tools
from .server import server

User = get_user_model()
PROJECT_ROOT = Path(__file__).resolve().parent.parent


async def _call_server_tool(name, arguments=None):
    async with Client(server) as client:
        return await client.call_tool(name, arguments)


async def _list_tools_from_stdio_server(environment):
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.server"],
        env=environment,
        cwd=PROJECT_ROOT,
    )
    async with Client(parameters) as client:
        return await client.list_tools()


class TaskToolsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="mcp_admin",
            email="mcp_admin@example.test",
            password="unused-password",
            role=User.ROLE_ADMIN,
        )
        self.member = User.objects.create_user(
            username="mcp_member",
            email="mcp_member@example.test",
            password="unused-password",
            role=User.ROLE_MEMBER,
        )
        self.other_member = User.objects.create_user(
            username="mcp_other",
            email="mcp_other@example.test",
            password="unused-password",
            role=User.ROLE_MEMBER,
        )
        self.own_task = Task.objects.create(
            title="Own task",
            description="Visible to the assigned member.",
            status=Task.STATUS_TODO,
            priority=Task.PRIORITY_MEDIUM,
            due_date=timezone.localdate() - timedelta(days=1),
            created_by=self.admin,
            assigned_to=self.member,
        )
        self.other_task = Task.objects.create(
            title="Other task",
            description="Not visible to the member.",
            status=Task.STATUS_IN_PROGRESS,
            priority=Task.PRIORITY_HIGH,
            created_by=self.admin,
            assigned_to=self.other_member,
        )
        self.user_environment = patch.dict(os.environ, {"TASKFLOW_MCP_USER": self.member.username})
        self.user_environment.start()
        self.addCleanup(self.user_environment.stop)

    def call_tool(self, name, arguments=None):
        return async_to_sync(_call_server_tool)(name, arguments)

    def test_stdio_sdk_client_starts_server_and_lists_tools(self):
        result = async_to_sync(_list_tools_from_stdio_server)({
            "TASKFLOW_MCP_USER": self.member.username,
        })

        self.assertEqual(
            {tool.name for tool in result.tools},
            {
                "list_my_tasks",
                "get_task_details",
                "list_overdue_tasks",
                "get_task_summary",
                "create_task",
                "update_task_status",
                "assign_task",
            },
        )

    def test_sdk_client_valid_arguments_and_admin_operations(self):
        os.environ["TASKFLOW_MCP_USER"] = self.admin.username
        project = Project.objects.create(name="MCP project", created_by=self.admin)
        label = Label.objects.create(name="MCP label", color="#123456")
        self.own_task.project = project
        self.own_task.save(update_fields=["project", "updated_at"])
        self.own_task.labels.add(label)
        checklist = TaskChecklistItem.objects.create(
            task=self.own_task,
            title="MCP-visible checklist item",
            position=1,
        )

        created = self.call_tool("create_task", {
            "title": "SDK-created task",
            "description": "Integration test task.",
            "status": Task.STATUS_TODO,
            "priority": Task.PRIORITY_HIGH,
            "due_date": (timezone.localdate() - timedelta(days=1)).isoformat(),
            "assignee_username": self.member.username,
        })
        self.assertFalse(created.is_error)
        task_data = created.structured_content["task"]
        task = Task.objects.get(pk=task_data["id"])
        self.assertEqual(task.title, "SDK-created task")
        self.assertEqual(task.created_by, self.admin)
        self.assertEqual(task.assigned_to, self.member)
        self.assertTrue(task.is_overdue)
        self.assertTrue(TaskActivityLog.objects.filter(task=task, action="CREATED").exists())
        self.assertTrue(Notification.objects.filter(
            task=task,
            recipient=self.member,
            notification_type=Notification.TYPE_ASSIGNMENT,
        ).exists())

        os.environ["TASKFLOW_MCP_USER"] = self.member.username
        listed = self.call_tool("list_my_tasks", {"status": Task.STATUS_TODO, "limit": 10})
        self.assertFalse(listed.is_error)
        self.assertIn(task.pk, [record["id"] for record in listed.structured_content["tasks"]])
        own_record = next(
            record
            for record in listed.structured_content["tasks"]
            if record["id"] == self.own_task.pk
        )
        self.assertEqual(own_record["project"], project.name)
        self.assertEqual(own_record["labels"][0]["name"], label.name)
        os.environ["TASKFLOW_MCP_USER"] = self.admin.username

        details = self.call_tool("get_task_details", {"task_id": task.pk})
        self.assertFalse(details.is_error)
        self.assertEqual(details.structured_content["title"], task.title)
        details_with_relations = self.call_tool("get_task_details", {"task_id": self.own_task.pk})
        self.assertEqual(details_with_relations.structured_content["project"], project.name)
        self.assertEqual(details_with_relations.structured_content["labels"], [
            {"name": label.name, "color": label.color},
        ])
        self.assertEqual(
            details_with_relations.structured_content["checklist_items"][0]["id"],
            checklist.pk,
        )

        overdue = self.call_tool("list_overdue_tasks", {"limit": 10})
        self.assertIn(task.pk, [record["id"] for record in overdue.structured_content["tasks"]])

        summary = self.call_tool("get_task_summary")
        self.assertEqual(summary.structured_content["scope"], "all_tasks")
        self.assertEqual(summary.structured_content["total"], 3)

        updated = self.call_tool("update_task_status", {
            "task_id": task.pk,
            "status": Task.STATUS_IN_PROGRESS,
        })
        self.assertFalse(updated.is_error)
        self.assertEqual(updated.structured_content["task"]["status"], Task.STATUS_IN_PROGRESS)
        self.assertTrue(TaskActivityLog.objects.filter(
            task=task,
            action="STATUS_CHANGE",
        ).exists())
        self.assertTrue(Notification.objects.filter(
            task=task,
            recipient=self.member,
            notification_type=Notification.TYPE_STATUS_CHANGE,
        ).exists())

        assigned = self.call_tool("assign_task", {
            "task_id": task.pk,
            "assignee_username": self.other_member.username,
        })
        self.assertFalse(assigned.is_error)
        task.refresh_from_db()
        self.assertEqual(task.assigned_to, self.other_member)
        self.assertTrue(TaskActivityLog.objects.filter(
            task=task,
            action="UPDATED",
            details__contains="Reassigned to",
        ).exists())
        self.assertTrue(Notification.objects.filter(
            task=task,
            recipient=self.other_member,
            notification_type=Notification.TYPE_ASSIGNMENT,
        ).exists())

    def test_sdk_client_rejects_bad_choices_dates_and_missing_tasks(self):
        os.environ["TASKFLOW_MCP_USER"] = self.admin.username

        invalid_arguments = (
            {"title": "Bad status", "status": "BLOCKED"},
            {"title": "Bad priority", "priority": "URGENT"},
            {"title": "Invalid date", "due_date": "2025-2-3"},
            {"title": "Invalid date value", "due_date": "2025-02-30"},
        )
        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments):
                result = self.call_tool("create_task", arguments)
                self.assertTrue(result.is_error)
                self.assertFalse(Task.objects.filter(title=arguments["title"]).exists())

        missing = self.call_tool("get_task_details", {"task_id": 999_999})
        self.assertTrue(missing.is_error)
        self.assertIn("Task not found.", missing.content[0].text)

        invalid_status = self.call_tool("update_task_status", {
            "task_id": self.own_task.pk,
            "status": "BLOCKED",
        })
        self.assertTrue(invalid_status.is_error)
        self.own_task.refresh_from_db()
        self.assertEqual(self.own_task.status, Task.STATUS_TODO)

    def test_sdk_client_refuses_inactive_and_unknown_acting_users(self):
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])

        inactive_result = self.call_tool("get_task_summary")
        self.assertTrue(inactive_result.is_error)
        self.assertIn("missing or inactive", inactive_result.content[0].text)

        os.environ["TASKFLOW_MCP_USER"] = "unknown_mcp_user"
        unknown_result = self.call_tool("get_task_summary")
        self.assertTrue(unknown_result.is_error)
        self.assertIn("missing or inactive", unknown_result.content[0].text)

    def test_sdk_client_member_cannot_access_another_members_task(self):
        details = self.call_tool("get_task_details", {"task_id": self.other_task.pk})
        self.assertTrue(details.is_error)
        self.assertIn("Task not found.", details.content[0].text)

        update = self.call_tool("update_task_status", {
            "task_id": self.other_task.pk,
            "status": Task.STATUS_COMPLETED,
        })
        self.assertTrue(update.is_error)
        self.assertIn("Task not found.", update.content[0].text)

        assign = self.call_tool("assign_task", {
            "task_id": self.other_task.pk,
            "assignee_username": self.member.username,
        })
        self.assertTrue(assign.is_error)
        self.assertIn("Only administrators", assign.content[0].text)

        self.other_task.refresh_from_db()
        self.assertEqual(self.other_task.status, Task.STATUS_IN_PROGRESS)
        self.assertEqual(self.other_task.assigned_to, self.other_member)
        self.assertFalse(TaskActivityLog.objects.filter(task=self.other_task).exists())
        self.assertFalse(Notification.objects.filter(task=self.other_task).exists())

    def test_sdk_client_member_cannot_create_or_assign_tasks(self):
        created = self.call_tool("create_task", {"title": "Member-created"})
        self.assertTrue(created.is_error)
        self.assertIn("Only administrators", created.content[0].text)
        self.assertFalse(Task.objects.filter(title="Member-created").exists())

        assigned = self.call_tool("assign_task", {
            "task_id": self.own_task.pk,
            "assignee_username": self.other_member.username,
        })
        self.assertTrue(assigned.is_error)
        self.assertIn("Only administrators", assigned.content[0].text)

        self.own_task.refresh_from_db()
        self.assertEqual(self.own_task.assigned_to, self.member)
        self.assertFalse(TaskActivityLog.objects.filter(
            task=self.own_task,
            action="UPDATED",
        ).exists())

    def test_member_task_lists_and_summary_are_scoped(self):
        task_list = tools.list_my_tasks()
        self.assertEqual([task["id"] for task in task_list["tasks"]], [self.own_task.pk])

        overdue = tools.list_overdue_tasks()
        self.assertEqual([task["id"] for task in overdue["tasks"]], [self.own_task.pk])

        summary = tools.get_task_summary()
        self.assertEqual(summary["scope"], "assigned_to_me")
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["overdue"], 1)

    def test_admin_summary_includes_all_tasks(self):
        os.environ["TASKFLOW_MCP_USER"] = self.admin.username

        summary = tools.get_task_summary()

        self.assertEqual(summary["scope"], "all_tasks")
        self.assertEqual(summary["total"], 2)

    def test_hidden_and_missing_tasks_have_same_not_found_error(self):
        messages = []
        for task_id in (self.other_task.pk, self.other_task.pk + 1000):
            with self.assertRaises(ToolError) as error:
                tools.get_task_details(task_id)
            messages.append(str(error.exception))

        self.assertEqual(messages, ["Task not found.", "Task not found."])

    def test_active_user_is_reloaded_and_missing_or_inactive_identity_is_refused(self):
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])

        with self.assertRaisesRegex(ToolError, "missing or inactive"):
            tools.get_task_summary()

        del os.environ["TASKFLOW_MCP_USER"]
        with self.assertRaisesRegex(ToolError, "TASKFLOW_MCP_USER is not set"):
            tools.get_task_summary()

    def test_member_can_change_only_the_status_of_an_assigned_task(self):
        result = tools.update_task_status(self.own_task.pk, Task.STATUS_COMPLETED)

        self.own_task.refresh_from_db()
        self.assertTrue(result["changed"])
        self.assertEqual(self.own_task.status, Task.STATUS_COMPLETED)
        self.assertIsNotNone(self.own_task.completed_at)
        self.assertTrue(TaskActivityLog.objects.filter(
            task=self.own_task,
            actor=self.member,
            action="STATUS_CHANGE",
        ).exists())
        self.assertTrue(Notification.objects.filter(
            task=self.own_task,
            recipient=self.admin,
            notification_type=Notification.TYPE_STATUS_CHANGE,
        ).exists())

        with self.assertRaisesRegex(ToolError, "Task not found"):
            tools.update_task_status(self.other_task.pk, Task.STATUS_COMPLETED)

    def test_create_task_reuses_validation_logs_and_assignment_notifications(self):
        os.environ["TASKFLOW_MCP_USER"] = self.admin.username

        result = tools.create_task(
            title="MCP-created task",
            description="Created through the local MCP server.",
            priority=Task.PRIORITY_HIGH,
            due_date=timezone.localdate().isoformat(),
            assignee_username=self.member.username,
        )

        task = Task.objects.get(pk=result["task"]["id"])
        self.assertEqual(task.created_by, self.admin)
        self.assertEqual(task.assigned_to, self.member)
        self.assertTrue(TaskActivityLog.objects.filter(
            task=task,
            action="CREATED",
            details__contains="via MCP",
        ).exists())
        self.assertTrue(Notification.objects.filter(
            task=task,
            recipient=self.member,
            notification_type=Notification.TYPE_ASSIGNMENT,
        ).exists())

    def test_admin_assignment_reuses_activity_and_notification_behavior(self):
        os.environ["TASKFLOW_MCP_USER"] = self.admin.username

        result = tools.assign_task(self.own_task.pk, self.other_member.username)

        self.own_task.refresh_from_db()
        self.assertTrue(result["changed"])
        self.assertEqual(self.own_task.assigned_to, self.other_member)
        self.assertTrue(TaskActivityLog.objects.filter(
            task=self.own_task,
            actor=self.admin,
            action="UPDATED",
            details__contains="Reassigned to",
        ).exists())
        self.assertTrue(Notification.objects.filter(
            task=self.own_task,
            recipient=self.other_member,
            notification_type=Notification.TYPE_ASSIGNMENT,
        ).exists())

        inactive_user = User.objects.create_user(
            username="mcp_inactive",
            email="mcp_inactive@example.test",
            is_active=False,
        )
        with self.assertRaisesRegex(ToolError, "active TaskFlow user"):
            tools.assign_task(self.own_task.pk, inactive_user.username)

    def test_only_admins_can_create_or_assign_tasks(self):
        with self.assertRaisesRegex(ToolError, "Only administrators"):
            tools.create_task("Denied task")
        with self.assertRaisesRegex(ToolError, "Only administrators"):
            tools.assign_task(self.own_task.pk, self.other_member.username)

    def test_task_input_validation_rejects_bad_choices_dates_and_lengths(self):
        os.environ["TASKFLOW_MCP_USER"] = self.admin.username

        invalid_inputs = (
            {"title": "Bad status", "status": "BLOCKED"},
            {"title": "Bad priority", "priority": "URGENT"},
            {"title": "Bad date", "due_date": "2025-2-3"},
            {"title": "x" * 256},
            {"title": "Long description", "description": "x" * 10_001},
        )
        for arguments in invalid_inputs:
            with self.subTest(arguments=list(arguments)):
                with self.assertRaises(ToolError):
                    tools.create_task(**arguments)

        with self.assertRaises(ToolError):
            tools.update_task_status(self.own_task.pk, "BLOCKED")

        self.assertFalse(Task.objects.filter(title="Bad status").exists())
