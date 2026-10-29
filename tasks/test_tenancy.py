from datetime import timedelta
import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from organizations.models import Organization, OrganizationMembership
from organizations.services import (
    add_user_to_organization,
    ensure_default_organization,
)
from tasks.forms import LabelForm, ProjectForm, TaskForm
from tasks.models import Label, Project, Task, TaskComment
from mcp_server import tools as mcp_tools
from mcp.server.mcpserver.exceptions import ToolError

User = get_user_model()


class TenantIsolationTests(TestCase):
    def setUp(self):
        # Create Organizations A and B
        self.org_a = Organization.objects.create(name="Acme Corp", slug="acme")
        self.org_b = Organization.objects.create(name="Beta Industries", slug="beta")

        # Users for Org A
        self.owner_a = User.objects.create_user(
            username="owner_a",
            email="owner_a@acme.test",
            password="password123",
            role=User.ROLE_ADMIN,
            first_name="Owner",
            last_name="A",
        )
        self.admin_a = User.objects.create_user(
            username="admin_a",
            email="admin_a@acme.test",
            password="password123",
            role=User.ROLE_ADMIN,
            first_name="Admin",
            last_name="A",
        )
        self.member_a = User.objects.create_user(
            username="member_a",
            email="member_a@acme.test",
            password="password123",
            role=User.ROLE_MEMBER,
            first_name="Member",
            last_name="A",
        )

        # Users for Org B
        self.owner_b = User.objects.create_user(
            username="owner_b",
            email="owner_b@beta.test",
            password="password123",
            role=User.ROLE_ADMIN,
            first_name="Owner",
            last_name="B",
        )
        self.member_b = User.objects.create_user(
            username="member_b",
            email="member_b@beta.test",
            password="password123",
            role=User.ROLE_MEMBER,
            first_name="Member",
            last_name="B",
        )

        # Dual-member user
        self.dual_user = User.objects.create_user(
            username="dual_user",
            email="dual@test.com",
            password="password123",
            role=User.ROLE_MEMBER,
            first_name="Dual",
            last_name="User",
        )

        # Set up memberships
        self.mem_owner_a = OrganizationMembership.objects.create(
            organization=self.org_a,
            user=self.owner_a,
            role=OrganizationMembership.ROLE_OWNER,
            is_active=True,
        )
        self.mem_admin_a = OrganizationMembership.objects.create(
            organization=self.org_a,
            user=self.admin_a,
            role=OrganizationMembership.ROLE_ADMIN,
            is_active=True,
        )
        self.mem_member_a = OrganizationMembership.objects.create(
            organization=self.org_a,
            user=self.member_a,
            role=OrganizationMembership.ROLE_MEMBER,
            is_active=True,
        )

        self.mem_owner_b = OrganizationMembership.objects.create(
            organization=self.org_b,
            user=self.owner_b,
            role=OrganizationMembership.ROLE_OWNER,
            is_active=True,
        )
        self.mem_member_b = OrganizationMembership.objects.create(
            organization=self.org_b,
            user=self.member_b,
            role=OrganizationMembership.ROLE_MEMBER,
            is_active=True,
        )

        self.mem_dual_a = OrganizationMembership.objects.create(
            organization=self.org_a,
            user=self.dual_user,
            role=OrganizationMembership.ROLE_MEMBER,
            is_active=True,
        )
        self.mem_dual_b = OrganizationMembership.objects.create(
            organization=self.org_b,
            user=self.dual_user,
            role=OrganizationMembership.ROLE_ADMIN,
            is_active=True,
        )

        # Projects and Labels
        self.project_a = Project.objects.create(
            organization=self.org_a,
            name="Alpha Project",
            description="Org A Project",
            created_by=self.owner_a,
        )
        self.label_a = Label.objects.create(
            organization=self.org_a,
            name="Alpha Label",
            color="#4f46e5",
        )

        self.project_b = Project.objects.create(
            organization=self.org_b,
            name="Beta Project",
            description="Org B Project",
            created_by=self.owner_b,
        )
        self.label_b = Label.objects.create(
            organization=self.org_b,
            name="Beta Label",
            color="#ef4444",
        )

        # Tasks
        self.task_a = Task.objects.create(
            organization=self.org_a,
            title="Task for Org A",
            description="Internal Acme Task",
            status=Task.STATUS_TODO,
            priority=Task.PRIORITY_HIGH,
            project=self.project_a,
            created_by=self.owner_a,
            assigned_to=self.member_a,
            due_date=timezone.localdate() + timedelta(days=2),
        )
        self.task_a.labels.add(self.label_a)

        self.task_b = Task.objects.create(
            organization=self.org_b,
            title="Task for Org B",
            description="Internal Beta Task",
            status=Task.STATUS_TODO,
            priority=Task.PRIORITY_HIGH,
            project=self.project_b,
            created_by=self.owner_b,
            assigned_to=self.member_b,
            due_date=timezone.localdate() + timedelta(days=2),
        )
        self.task_b.labels.add(self.label_b)

    # 1. Organization context & resolution
    def test_middleware_resolves_active_organization(self):
        self.client.login(username="admin_a", password="password123")
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_organization"], self.org_a)
        self.assertEqual(response.context["active_membership"], self.mem_admin_a)

    def test_explicit_unauthorized_org_rejected_safely(self):
        # Admin A tries to access Org B via header
        self.client.login(username="admin_a", password="password123")
        response = self.client.get(
            reverse("dashboard"),
            HTTP_X_ORGANIZATION_SLUG="beta",
        )
        # Web requests safely fall back to the user's authorized membership
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_organization"], self.org_a)

        # API requests strictly reject unauthorized org access with 403
        api_client = APIClient()
        api_client.force_authenticate(user=self.admin_a)
        api_response = api_client.get(
            "/api/v1/tasks/",
            HTTP_X_ORGANIZATION_SLUG="beta",
        )
        self.assertEqual(api_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_switch_organization_view(self):
        self.client.login(username="dual_user", password="password123")
        # Dual user starts in Org A
        res = self.client.get(reverse("dashboard"))
        self.assertEqual(res.context["active_organization"], self.org_a)

        # Switch to Org B
        switch_url = reverse("switch_organization", args=[self.org_b.id])
        res = self.client.post(switch_url)
        self.assertRedirects(res, reverse("dashboard"))

        # Context is now Org B
        res = self.client.get(reverse("dashboard"))
        self.assertEqual(res.context["active_organization"], self.org_b)

        # Cannot switch to an unauthorized organization
        unauth_org = Organization.objects.create(name="Gamma", slug="gamma")
        switch_url = reverse("switch_organization", args=[unauth_org.id])
        res = self.client.post(switch_url)
        self.assertEqual(res.status_code, 403)

    # 2. Web views tenant isolation
    def test_dashboard_and_task_list_isolated_between_tenants(self):
        self.client.login(username="admin_a", password="password123")
        res = self.client.get(reverse("task_list"))
        self.assertContains(res, self.task_a.title)
        self.assertNotContains(res, self.task_b.title)

        # Org B admin only sees Org B
        self.client.login(username="owner_b", password="password123")
        res = self.client.get(reverse("task_list"))
        self.assertContains(res, self.task_b.title)
        self.assertNotContains(res, self.task_a.title)

    def test_task_detail_edit_delete_isolated(self):
        self.client.login(username="admin_a", password="password123")
        # Cannot view Org B task
        res = self.client.get(reverse("task_detail", args=[self.task_b.pk]))
        self.assertEqual(res.status_code, 404)

        # Cannot edit Org B task
        res = self.client.get(reverse("task_edit", args=[self.task_b.pk]))
        self.assertEqual(res.status_code, 404)

        # Cannot delete Org B task
        res = self.client.post(reverse("task_delete", args=[self.task_b.pk]))
        self.assertEqual(res.status_code, 404)

        # Cannot update status of Org B task
        res = self.client.post(
            reverse("update_task_status", args=[self.task_b.pk]),
            {"status": Task.STATUS_COMPLETED},
        )
        self.assertEqual(res.status_code, 404)

    def test_kanban_and_calendar_and_search_isolated(self):
        self.client.login(username="admin_a", password="password123")
        # Kanban
        res = self.client.get(reverse("kanban"))
        self.assertContains(res, self.task_a.title)
        self.assertNotContains(res, self.task_b.title)

        # Calendar
        res = self.client.get(reverse("task_calendar"))
        self.assertContains(res, self.task_a.title)
        self.assertNotContains(res, self.task_b.title)

        # Palette search
        res = self.client.get(reverse("task_palette_search"), {"q": "Org B"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json()["results"]), 0)

        res = self.client.get(reverse("task_palette_search"), {"q": "Org A"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json()["results"]), 1)

    # 3. Form validation and per-org uniqueness
    def test_project_and_label_uniqueness_scoped_to_organization(self):
        # Allowed: Same project name in different organizations
        p_b_duplicate = Project(
            organization=self.org_b,
            name="Alpha Project",
            created_by=self.owner_b,
        )
        p_b_duplicate.save()
        self.assertEqual(Project.objects.filter(name="Alpha Project").count(), 2)

        # Disallowed: Duplicate project name within same organization
        form = ProjectForm(
            data={"name": "Alpha Project", "description": "Duplicate in Org A"},
            organization=self.org_a,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)

        # Allowed: Same label name in different organizations
        l_b_duplicate = Label(
            organization=self.org_b,
            name="Alpha Label",
            color="#22c55e",
        )
        l_b_duplicate.save()
        self.assertEqual(Label.objects.filter(name="Alpha Label").count(), 2)

        # Disallowed: Duplicate label name within same organization
        label_form = LabelForm(
            data={"name": "Alpha Label", "color": "#22c55e"},
            organization=self.org_a,
        )
        self.assertFalse(label_form.is_valid())
        self.assertIn("name", label_form.errors)

    def test_task_form_rejects_cross_tenant_relations(self):
        # Cannot assign Project from Org B to Org A task
        form = TaskForm(
            data={
                "title": "Cross Tenant Task",
                "status": Task.STATUS_TODO,
                "priority": Task.PRIORITY_MEDIUM,
                "project": self.project_b.pk,
            },
            organization=self.org_a,
            user=self.admin_a,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("project", form.errors)

        # Cannot assign Label from Org B to Org A task
        form = TaskForm(
            data={
                "title": "Cross Tenant Task",
                "status": Task.STATUS_TODO,
                "priority": Task.PRIORITY_MEDIUM,
                "labels": [self.label_b.pk],
            },
            organization=self.org_a,
            user=self.admin_a,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("labels", form.errors)

        # Cannot assign User who is only in Org B to Org A task
        form = TaskForm(
            data={
                "title": "Cross Tenant Task",
                "status": Task.STATUS_TODO,
                "priority": Task.PRIORITY_MEDIUM,
                "assigned_to": self.member_b.pk,
            },
            organization=self.org_a,
            user=self.admin_a,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("assigned_to", form.errors)

    # 4. Team management and last-owner protection
    def test_team_management_shows_only_tenant_members(self):
        self.client.login(username="owner_a", password="password123")
        res = self.client.get(reverse("user_management"))
        self.assertContains(res, "owner_a")
        self.assertContains(res, "admin_a")
        self.assertContains(res, "member_a")
        self.assertNotContains(res, "owner_b")
        self.assertNotContains(res, "member_b")

    def test_last_owner_deactivation_protection(self):
        self.client.login(username="owner_a", password="password123")
        # Promote admin_a to second owner
        self.mem_admin_a.role = OrganizationMembership.ROLE_OWNER
        self.mem_admin_a.save(update_fields=["role"])
        mem_second_owner = self.mem_admin_a

        # Deactivating one owner is allowed when 2 owners exist
        toggle_url = reverse("toggle_user_active", args=[self.admin_a.id])
        res = self.client.post(toggle_url)
        self.assertEqual(res.status_code, 302)
        mem_second_owner.refresh_from_db()
        self.assertFalse(mem_second_owner.is_active)

        # Deactivating the last active owner is blocked
        # (owner_a cannot deactivate self via UI, but if another admin tries to deactivate owner_a)
        mem_second_owner.role = OrganizationMembership.ROLE_ADMIN
        mem_second_owner.is_active = True
        mem_second_owner.save()
        self.admin_a.is_active = True
        self.admin_a.save()

        self.client.login(username="admin_a", password="password123")
        toggle_url = reverse("toggle_user_active", args=[self.owner_a.id])
        res = self.client.post(toggle_url, follow=True)
        self.assertContains(res, "Cannot deactivate the last active owner")
        self.mem_owner_a.refresh_from_db()
        self.assertTrue(self.mem_owner_a.is_active)

    # 5. REST API Multi-tenancy
    def test_api_viewset_queryset_isolation(self):
        api_client = APIClient()
        api_client.force_authenticate(user=self.admin_a)

        # GET /api/v1/tasks/ with X-Organization-Slug=acme
        res = api_client.get("/api/v1/tasks/", HTTP_X_ORGANIZATION_SLUG="acme")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        task_ids = [t["id"] for t in res.data["results"]]
        self.assertIn(self.task_a.id, task_ids)
        self.assertNotIn(self.task_b.id, task_ids)

        # GET /api/v1/tasks/{task_b.id}/ returns 404
        res = api_client.get(f"/api/v1/tasks/{self.task_b.id}/", HTTP_X_ORGANIZATION_SLUG="acme")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # GET /api/v1/projects/ returns only Org A projects
        res = api_client.get("/api/v1/projects/", HTTP_X_ORGANIZATION_SLUG="acme")
        project_ids = [p["id"] for p in res.data["results"]]
        self.assertIn(self.project_a.id, project_ids)
        self.assertNotIn(self.project_b.id, project_ids)

        # GET /api/v1/labels/ returns only Org A labels
        res = api_client.get("/api/v1/labels/", HTTP_X_ORGANIZATION_SLUG="acme")
        label_ids = [l["id"] for l in res.data["results"]]
        self.assertIn(self.label_a.id, label_ids)
        self.assertNotIn(self.label_b.id, label_ids)

    def test_api_rejects_cross_tenant_foreign_keys(self):
        api_client = APIClient()
        api_client.force_authenticate(user=self.admin_a)

        # Attempt to create task in Org A with Org B's project
        res = api_client.post(
            "/api/v1/tasks/",
            {
                "title": "Malicious Cross-Tenant Task",
                "status": "TODO",
                "priority": "HIGH",
                "project": self.project_b.id,
            },
            HTTP_X_ORGANIZATION_SLUG="acme",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("project", res.data)

        # Attempt to create task in Org A with Org B's assignee
        res = api_client.post(
            "/api/v1/tasks/",
            {
                "title": "Malicious Cross-Tenant Task",
                "status": "TODO",
                "priority": "HIGH",
                "assigned_to": self.member_b.id,
            },
            HTTP_X_ORGANIZATION_SLUG="acme",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("assigned_to", res.data)

    # 6. AI Assistant & MCP isolation
    def test_mcp_scoped_strictly_to_active_organization(self):
        with patch.dict(os.environ, {
            "TASKFLOW_MCP_USER": self.admin_a.username,
            "TASKFLOW_MCP_ORG": "acme",
        }):
            # search_tasks only finds Org A tasks
            result = mcp_tools.search_tasks(keyword="Task")
            task_ids = [t["id"] for t in result["tasks"]]
            self.assertIn(self.task_a.id, task_ids)
            self.assertNotIn(self.task_b.id, task_ids)

            # get_task_details rejects Org B task
            with self.assertRaises(ToolError):
                mcp_tools.get_task_details(self.task_b.id)

            # create_task automatically sets organization to Org A
            created = mcp_tools.create_task(title="MCP Org A Task")
            new_task = Task.objects.get(pk=created["task"]["id"])
            self.assertEqual(new_task.organization, self.org_a)

            # assign_task rejects Org B assignee
            with self.assertRaises(ToolError):
                mcp_tools.assign_task(self.task_a.id, self.member_b.username)

    def test_mcp_rejects_unauthorized_organization(self):
        with patch.dict(os.environ, {
            "TASKFLOW_MCP_USER": self.admin_a.username,
            "TASKFLOW_MCP_ORG": "beta",  # Admin A has no membership in Org B
        }):
            with self.assertRaises(ToolError):
                mcp_tools.list_my_tasks()
