# TaskFlow - Testing Strategy & Quality Assurance Plan

## 1. Testing Strategy Overview
Quality assurance for TaskFlow employs a pyramid structure focusing on unit tests, integration tests for key business workflows, API verification, and UI/client validation.

---

## 2. Test Suites

### 2.1 Unit Tests (`accounts` & `tasks` models)
- **User Model Tests:**
  - Verify user creation, roles (`ADMIN` vs. `MEMBER`), and avatar initial generation.
  - Verify password hashing and email uniqueness constraints.
- **Task Model Tests:**
  - Verify default status is `TODO` and default priority is `MEDIUM`.
  - Verify overdue logic (`is_overdue` returns true only if `due_date < today` and `status != COMPLETED`).
  - Verify automatic `completed_at` timestamp setting when status moves to `COMPLETED`.
- **Collaboration Model Tests:**
  - Verify optional project links, label associations, checklist ordering, and checklist completion progress.
  - Verify labels reject invalid hex colours and project/label forms enforce unique names.
  - Verify checklist completion never changes task status.
- **Comment Model Tests:**
  - Verify parent-child nested comment relationship.

### 2.2 Functional & Permission Tests
- **Member Access Boundaries:**
  - Members cannot access `/users/` admin management route (returns 403 or redirect).
  - Members cannot delete tasks created by other users without admin permissions.
  - Non-authenticated requests to protected endpoints redirect to `/accounts/login/` or return 401/403.
- **Admin Capabilities:**
  - Admin can update any task, reassign tasks, and access workload analytics.
- **Projects, Labels, and Checklists:**
  - Admin creates, edits, archives/restores projects and manages labels/checklist content.
  - Members see only projects containing their assigned tasks and cannot manage projects, labels, or checklist content/order.
  - Members can toggle checklist completion only for assigned tasks; inaccessible checklist/task objects return 404.
  - Task list and Kanban project/label filters retain selected values; checklist progress appears on detail, list, and board cards.
- **Calendar, Search, and Export:**
  - Calendar month navigation includes due-date tasks only and highlights today; members see assigned tasks only while admins can filter by assignee.
  - Command-palette search is authenticated and never returns tasks outside the task-list visibility scope.
  - CSV export is administrator-only, respects list filters, uses a safe attachment filename, and escapes formula-triggering cells.
  - Verify the theme honors system preference by default, persists explicit changes, and initializes before first paint on auth, landing, dashboard, and chart pages.
  - Verify Ctrl/Cmd+K, Escape, keyboard result navigation, the shortcuts dialog, and visible focus behavior.

### 2.3 API Integration Tests (DRF)
- **Task API (`/api/v1/tasks/`):**
  - `GET /api/v1/tasks/` with filters (status, priority, search).
  - `POST /api/v1/tasks/` creates new task and logs audit entry.
  - `PATCH /api/v1/tasks/{id}/update-status/` updates status and records timestamp.
- **Comments API (`/api/v1/tasks/{id}/comments/`):**
  - Add root comment and threaded reply.
  - Triggers notification to task assignee.
- **Notifications API (`/api/v1/notifications/`):**
  - Mark single notification as read.
  - Mark all notifications as read.
- **Analytics API (`/api/v1/analytics/overview/`):**
  - Verify aggregate metrics calculation matches database counts.
- **Collaboration APIs:**
  - Verify administrator CRUD/assignment for projects, labels, and checklist items.
  - Verify project visibility is member-scoped, hidden projects/items return 404, and members can PATCH only checklist completion on assigned tasks.
  - Verify task responses include project, label IDs, and ordered checklist items without per-task related-object queries.

### 2.4 Browser & Interactive QA
- **Kanban Drag-and-Drop:**
  - Test dragging cards between columns (To Do -> In Progress -> Completed).
  - Verify column counters update immediately.
  - Test server error rollback.
- **Responsive Layout:**
  - Verify desktop sidebar vs mobile toggle drawer.
  - Verify tables and kanban horizontally scroll or wrap gracefully on viewports < 768px.
- **Form Validations:**
  - Test required fields, invalid due dates, and empty comment error messaging.

---

## 3. Running Automated Tests
```bash
# Run all tests
python manage.py test

# Run specific app tests
python manage.py test accounts
python manage.py test tasks
python manage.py test api
```
