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
- **Comment Model Tests:**
  - Verify parent-child nested comment relationship.

### 2.2 Functional & Permission Tests
- **Member Access Boundaries:**
  - Members cannot access `/users/` admin management route (returns 403 or redirect).
  - Members cannot delete tasks created by other users without admin permissions.
  - Non-authenticated requests to protected endpoints redirect to `/accounts/login/` or return 401/403.
- **Admin Capabilities:**
  - Admin can update any task, reassign tasks, and access workload analytics.

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
