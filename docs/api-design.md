# TaskFlow - REST API Specification

All API endpoints are prefixed with `/api/v1/`. Requests modifying state require standard Django CSRF token (`X-CSRFToken` header) or session authentication.

---

## 1. Authentication Endpoints

### 1.1 Current User Context
- **Endpoint:** `GET /api/v1/auth/me/`
- **Description:** Returns profile, permissions, and roles for currently authenticated user.
- **Response (200 OK):**
```json
{
  "id": 1,
  "username": "alex.admin",
  "email": "alex@taskflow.dev",
  "first_name": "Alex",
  "last_name": "Rivers",
  "role": "ADMIN",
  "department": "Product Management",
  "job_title": "Head of Product",
  "avatar_initials": "AR"
}
```

---

## 2. Task Endpoints

### 2.1 List / Filter Tasks
- **Endpoint:** `GET /api/v1/tasks/`
- **Query Parameters:**
  - `search`: Filter by keyword in title or description.
  - `status`: `TODO`, `IN_PROGRESS`, `COMPLETED`
  - `priority`: `LOW`, `MEDIUM`, `HIGH`
  - `assigned_to`: User ID or `"unassigned"`
  - `overdue`: `true` / `false`
  - `ordering`: `due_date`, `-created_at`, `priority`
- **Response (200 OK):** Array of task objects with author, assignee summary, overdue badge flag, and comment counts.

### 2.2 Create Task
- **Endpoint:** `POST /api/v1/tasks/`
- **Payload:**
```json
{
  "title": "Build user notification drawer",
  "description": "Implement drop-down with live unread indicators.",
  "status": "TODO",
  "priority": "HIGH",
  "due_date": "2026-11-05",
  "assigned_to": 4
}
```
- **Response:** `201 Created` with full task representation.

### 2.3 Retrieve Task Details
- **Endpoint:** `GET /api/v1/tasks/{id}/`
- **Response (200 OK):** Full task object, including comments thread, activity logs, and permissions for current user.

### 2.4 Update Task (Full / Partial)
- **Endpoint:** `PUT /api/v1/tasks/{id}/` or `PATCH /api/v1/tasks/{id}/`
- **Permissions:** Admin OR task creator OR task assignee (members cannot change assignment if not admin/creator).

### 2.5 Quick Status Update (Kanban Drag-and-Drop)
- **Endpoint:** `PATCH /api/v1/tasks/{id}/update-status/`
- **Payload:**
```json
{
  "status": "IN_PROGRESS"
}
```
- **Response (200 OK):**
```json
{
  "success": true,
  "id": 12,
  "status": "IN_PROGRESS",
  "completed_at": null,
  "message": "Task status updated to In Progress."
}
```

### 2.6 Delete Task
- **Endpoint:** `DELETE /api/v1/tasks/{id}/`
- **Permissions:** Admin or Task Creator.
- **Response:** `204 No Content`.

---

## 3. Comments & Threading Endpoints

### 3.1 List Comments for Task
- **Endpoint:** `GET /api/v1/tasks/{task_id}/comments/`
- **Response (200 OK):** Nested array of comments with children/replies.

### 3.2 Add Comment or Reply
- **Endpoint:** `POST /api/v1/tasks/{task_id}/comments/`
- **Payload:**
```json
{
  "content": "Wireframes have been uploaded to Drive.",
  "parent": 7
}
```
- **Response (201 Created):** Created comment with author details.

### 3.3 Delete Comment
- **Endpoint:** `DELETE /api/v1/comments/{id}/`
- **Permissions:** Author of comment or Admin.
- **Response:** `204 No Content`.

---

## 4. Notifications Endpoints

### 4.1 Get Notification Feed & Unread Count
- **Endpoint:** `GET /api/v1/notifications/`
- **Query Parameters:** `unread_only=true` (optional)
- **Response (200 OK):**
```json
{
  "unread_count": 3,
  "results": [
    {
      "id": 104,
      "actor": {"id": 2, "name": "Sarah Chen"},
      "verb": "assigned you to task 'Setup CI/CD pipeline'",
      "task_id": 18,
      "is_read": false,
      "created_at": "2026-10-27T10:15:00Z"
    }
  ]
}
```

### 4.2 Mark Single Notification as Read
- **Endpoint:** `POST /api/v1/notifications/{id}/mark-read/`
- **Response:** `200 OK`

### 4.3 Mark All Notifications as Read
- **Endpoint:** `POST /api/v1/notifications/mark-all-read/`
- **Response:** `200 OK` `{"marked": 3}`

---

## 5. Analytics & Dashboard Metrics Endpoints

### 5.1 Dashboard Summary Metrics
- **Endpoint:** `GET /api/v1/analytics/overview/`
- **Response (200 OK):**
```json
{
  "total_tasks": 42,
  "completed_tasks": 28,
  "in_progress_tasks": 10,
  "todo_tasks": 4,
  "overdue_tasks": 3,
  "completion_rate": 66.7,
  "status_distribution": {
    "TODO": 4,
    "IN_PROGRESS": 10,
    "COMPLETED": 28
  },
  "priority_distribution": {
    "LOW": 12,
    "MEDIUM": 20,
    "HIGH": 10
  }
}
```

### 5.2 Workload Distribution (Admin Only)
- **Endpoint:** `GET /api/v1/analytics/workload/`
- **Response (200 OK):**
```json
[
  {
    "user_id": 2,
    "name": "Sarah Chen",
    "department": "Engineering",
    "total_assigned": 9,
    "completed": 6,
    "in_progress": 2,
    "todo": 1,
    "overdue": 0
  }
]
```
