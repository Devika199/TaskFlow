# TaskFlow - System Requirements Specification

## 1. Executive Summary
**TaskFlow** is an enterprise-grade, modern SaaS Task Management and Team Collaboration platform engineered for cross-functional teams, project managers, and administrators. It bridges high-level oversight with day-to-day workflow tracking through interactive Kanban boards, role-based dashboards, task workload analytics, contextual comments, and automated notifications.

## 2. Stakeholders & User Personas
- **Administrator (Manager / Team Lead):** Oversees team member workloads, manages system users, assigns and reassigns tasks across projects, views holistic analytics (completion rate, overdue counts, bottleneck analysis).
- **Member (Collaborator / Individual Contributor):** Manages assigned tasks, updates progress via drag-and-drop Kanban or task lists, replies to comments, tracks upcoming deadlines, and receives notification alerts.

---

## 3. Functional Requirements

### 3.1 Authentication & Authorization (FR-AUTH)
- **FR-AUTH-01:** User registration with email, username, full name, role selection (or invitation default), and password validation.
- **FR-AUTH-02:** Secure session-based authentication with CSRF protection, secure cookie handling, and remember-me option.
- **FR-AUTH-03:** Role-Based Access Control (RBAC):
  - `ADMIN`: Full CRUD on all tasks, comments, user accounts, and system-wide analytics.
  - `MEMBER`: View all team tasks, create tasks, edit tasks they created or are assigned to, update task statuses (via Kanban or detail view), and write comments.
- **FR-AUTH-04:** Profile management (profile picture/avatar initials, bio, notification preferences).

### 3.2 Task Lifecycle & Management (FR-TASK)
- **FR-TASK-01:** Task creation with Title, Description (rich/markdown supported), Priority (`LOW`, `MEDIUM`, `HIGH`), Status (`TODO`, `IN_PROGRESS`, `COMPLETED`), Due Date, and Assignee.
- **FR-TASK-02:** Task editing, re-assignment, and deletion with confirmation dialogs.
- **FR-TASK-03:** Due date tracking with automatic overdue calculation and visual status tags (`Overdue`, `Due Today`, `Due Soon`).
- **FR-TASK-04:** Task activity audit logging (captures creation, assignment changes, status movements, and completion timestamps).

### 3.3 Interactive Kanban Board (FR-KANBAN)
- **FR-KANBAN-01:** 3-column workflow board (`To Do`, `In Progress`, `Done / Completed`).
- **FR-KANBAN-02:** Drag-and-drop task status transitions with asynchronous API sync and visual feedback.
- **FR-KANBAN-03:** Live column counters and task filters directly on the board.

### 3.4 Search, Filtering, and Sorting (FR-SEARCH)
- **FR-SEARCH-01:** Search by title or description keywords.
- **FR-SEARCH-02:** Multi-criteria filter: Status, Priority, Assignee, and Overdue status.
- **FR-SEARCH-03:** Sort by Due Date, Priority, Created Date, or Alphabetical.

### 3.5 Collaboration & Comments (FR-COMM)
- **FR-COMM-01:** Chronological task discussion feed.
- **FR-COMM-02:** Threaded/nested replies to specific comments.
- **FR-COMM-03:** Author badge, relative timestamp display ("2 hours ago"), and author-restricted deletion.

### 3.6 Notification System (FR-NOTIF)
- **FR-NOTIF-01:** Automated in-app notifications triggered on:
  - Task assignment to user.
  - Status change on a task created by or assigned to user.
  - New comment or reply on relevant task.
- **FR-NOTIF-02:** Unread notification count badge in top navigation.
- **FR-NOTIF-03:** Quick mark-as-read and mark-all-read capabilities via Fetch API.

### 3.7 Analytics & Workload Visibility (FR-METRICS)
- **FR-METRICS-01:** Key Performance Indicators: Total Tasks, Completed Rate %, In Progress Count, Overdue Count.
- **FR-METRICS-02:** Visual Charts:
  - Task Status Distribution (Donut Chart).
  - Priority Breakdown (Bar Chart).
  - Weekly Task Completion Velocity.
- **FR-METRICS-03:** Admin Workload Matrix: Member-by-member breakdown of active vs. completed tasks to prevent burn-out.

---

## 4. Non-Functional Requirements

### 4.1 Security & Compliance
- OWASP Top 10 mitigation: CSRF protection on all mutating calls, SQL Injection prevention via Django ORM, XSS mitigation with escaped templates.
- Strict authorization checks in views and REST viewsets verifying object-level ownership or admin status.
- Passwords hashed using PBKDF2 with SHA-256 (Django default).

### 4.2 Performance & Responsiveness
- Sub-200ms response times on list and Kanban queries with optimized Django `select_related` and `prefetch_related`.
- Mobile-first responsive UI adhering to Bootstrap 5 grid breakpoints (xs, sm, md, lg, xl, xxl).
- Asynchronous UI interactions via Fetch API without full page reload.

### 4.3 Reliability & Maintainability
- 100% adherence to standard Django application layout (`apps/` or modular structure).
- Database normalization to 3NF.
- Automated test coverage across models, forms, API endpoints, and authorization logic.
