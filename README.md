# TaskFlow - Enterprise SaaS Task Management Application

A modern, high-performance SaaS task management and team collaboration web application built for internship assessment. TaskFlow features an interactive Kanban board with drag-and-drop status syncing, role-based dashboards, workload distribution charts, contextual comment threads, in-app notifications, and Django REST Framework API endpoints.

---

## 🌟 Tech Stack & Key Technologies

- **Backend:** Python 3.12, Django 5.2, Django REST Framework (DRF)
- **Database:** SQLite 3 (Normalized to 3NF)
- **Frontend:** HTML5, CSS3, JavaScript (ES6+ / Fetch API), Bootstrap 5.3, Bootstrap Icons
- **Interactive UI Components:**
  - [SortableJS](https://sortablejs.github.io/Sortable/) for HTML5 Kanban drag-and-drop
  - [Chart.js](https://www.chartjs.org/) for analytics & workload visualization
  - [SweetAlert2](https://sweetalert2.github.io/) for toast alerts & confirmation dialogs
- **Security:** CSRF protection, PBKDF2 password hashing, RBAC (Role-Based Access Control)

---

## 🚀 Key Features

1. **Authentication & RBAC:**
   - Registration, secure session login, and logout.
   - Dual roles: `ADMIN` (system-wide oversight) and `MEMBER` (contributor).
   - One-click demo profile logins for immediate assessment.
2. **Interactive Kanban Board:**
   - 3 columns: `To Do`, `In Progress`, and `Completed`.
   - Smooth drag-and-drop with optimistic UI updates and REST API synchronization.
   - Dynamic column counter badges and board search/priority filters.
3. **Task Lifecycle Management:**
   - Rich task creation, editing, assignment, priority levels (`Low`, `Medium`, `High`), and due dates.
   - Automatic overdue indicators with warning badges (`Overdue`, `Due Today`, `Due Soon`).
4. **Collaboration & Discussion:**
   - Task discussion threads with nested comment replies.
   - Audit activity timeline tracking assignments, updates, and comments.
5. **In-App Notifications:**
   - Automated triggers on assignments, status updates, and comments.
   - Top navbar bell drawer with unread counter badge, 1-click "Mark all as read", and live sync.
6. **Analytics & Workload Visibility:**
   - KPI metrics cards: Total Tasks, In Progress, Overdue Bottlenecks, and Completion Rate %.
   - Interactive Status Distribution donut chart and Priority breakdown bar chart.
   - Admin Workload Matrix: Member-by-member capacity breakdown.
7. **REST API (`/api/v1/`):**
   - Full REST endpoints for tasks, status changes, comments, notifications, users, and analytics.

---

## ⚡ Instant Demo Credentials

For quick evaluation, use the one-click buttons on the login screen (`/login/`) or enter:

| Role | Username | Password | Email |
| :--- | :--- | :--- | :--- |
| **Administrator (Lead)** | `alex.admin` | `password123` | `alex@taskflow.dev` |
| **Team Member (Backend)** | `sarah.tech` | `password123` | `sarah.chen@taskflow.dev` |
| **Team Member (Frontend)** | `marcus.ui` | `password123` | `marcus.vance@taskflow.dev` |

---

## 🛠️ Getting Started & Setup

### 1. Prerequisites
- Python 3.10+ (tested on Python 3.12)
- Git

### 2. Install Dependencies
```bash
pip install django djangorestframework
```

### Admin registration access code (optional)
Public registration defaults to a member account. To enable admin account registration, set `ADMIN_REGISTRATION_CODE` in the server environment to a private value before starting Django. Copy `.env.example` as a reference; this project does not automatically load `.env` files.

PowerShell:
```powershell
$env:ADMIN_REGISTRATION_CODE = "set-a-private-code"
python manage.py runserver
```

macOS/Linux:
```bash
export ADMIN_REGISTRATION_CODE="set-a-private-code"
python manage.py runserver
```

If the variable is unset or empty, admin registration is disabled. Never commit a real access code.

### 3. Run Database Migrations
```bash
python manage.py migrate
```

### 4. Seed Realistic Demo Data
Populates realistic users, tasks, overdue deadlines, threaded comments, and notifications:
```bash
python manage.py seed_data
```

### 5. Run Automated Test Suite
```bash
python manage.py test
```
*Output: 20 passed tests covering authentication, RBAC, task lifecycle, kanban updates, comments, and DRF REST API.*

### 6. Start the Development Server
```bash
python manage.py runserver
```
Navigate to **[http://127.0.0.1:8000/](http://127.0.0.1:8000/)** in your browser.

---

## 📚 System Design Documentation

Comprehensive technical documentation is located in the `docs/` directory:
- [Requirements Specification](docs/requirements.md)
- [System Architecture & Mermaid Diagrams](docs/architecture.md)
- [Database Schema & ER Diagram](docs/database-design.md)
- [REST API Specification](docs/api-design.md)
- [Security Architecture & RBAC](docs/security.md)
- [Testing & Quality Assurance Plan](docs/testing-plan.md)

---

## 🔌 API Endpoints Summary

- `GET /api/v1/auth/me/` - Current authenticated user context
- `GET /api/v1/tasks/` - List/filter tasks (`?status=`, `?priority=`, `?assigned_to=`, `?overdue=`)
- `POST /api/v1/tasks/` - Create new task
- `PATCH /api/v1/tasks/{id}/update-status/` - Quick Kanban drag status update
- `GET, POST /api/v1/comments/` - Task comment thread & replies
- `GET /api/v1/notifications/` - User notifications feed & unread counter
- `POST /api/v1/notifications/mark-all-read/` - Mark all notifications as read
- `GET /api/v1/analytics/overview/` - High-level metrics & chart data
- `GET /api/v1/analytics/workload/` - Admin member workload breakdown
- `GET /api/v1/users/` - Active team member directory
