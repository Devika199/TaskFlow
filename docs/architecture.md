# TaskFlow - System Architecture

## 1. Architectural Overview
TaskFlow is built as a hybrid modern SaaS web application. It combines Django's robust server-side rendered (SSR) templates for core layout scaffolding, SEO, and fast initial paint with a Django REST Framework (DRF) JSON API and JavaScript (Fetch API + DOM manipulation) layer for fluid, reactive experiences (such as Kanban drag-and-drop, real-time comment insertion, and notification polling).

```mermaid
graph TD
    subgraph Client ["Client Tier (Browser)"]
        UI["Bootstrap 5 + Custom SaaS CSS"]
        KanbanEngine["SortableJS Kanban Drag-n-Drop"]
        ChartEngine["Chart.js Analytics Renderer"]
        AjaxEngine["Fetch API / AJAX Client"]
        ToastEngine["SweetAlert2 / Bootstrap Toasts"]
    end

    subgraph Gateway ["Web & Security Tier"]
        CSRF["Django CSRF Middleware"]
        AuthMiddleware["Authentication & Session Middleware"]
        RBAC["Role-Based Permission Guard"]
    end

    subgraph Application ["Django Application Tier (Python 3.12)"]
        Views["Django Template Views (HTML Rendering)"]
        DRF["Django REST Framework API ViewSets & Serializers"]
        MCP["Local MCP server (stdio)"]
        
        subgraph Domains ["Domain Modules"]
            AccountService["Accounts & User Management"]
            TaskService["Task Engine & Workflow Controller"]
            CommentService["Comment & Discussion Threading"]
            NotifService["Notification Dispatcher"]
            MetricService["Analytics & Workload Aggregator"]
        end
    end

    subgraph Data ["Data & Storage Tier"]
        ORM["Django ORM (Object Relational Mapping)"]
        DB[("SQLite 3 Relational Database")]
        Static["Static Files (CSS, JS, SVG, Fonts)"]
    end

    Client -->|HTTP GET/POST Requests| Gateway
    Client -->|Async Fetch API JSON Calls| Gateway
    Gateway --> Application
    Views --> Domains
    DRF --> Domains
    MCP --> Domains
    Domains --> ORM
    ORM --> DB
```

---

## 2. Component Breakdown

### 2.1 Client-Side Presentation
- **Bootstrap 5.3 & Custom Theme:** Customized with a SaaS dark/light palette, refined border radiuses, crisp typography (`Inter`), and modern elevation shadows.
- **Interactive Modules:**
  - `kanban.js`: Powered by SortableJS, triggers REST PATCH calls to `/api/tasks/{id}/update-status/` with roll-back state management on failure.
  - `comments.js`: Submits threaded comments via Fetch API, updating the DOM dynamically without page refresh.
  - `notifications.js`: Periodically syncs notification count and renders unread items inside the top navigation drawer.
  - `analytics.js`: Renders dynamic status, priority, and workload charts using Chart.js.

### 2.2 Security & Authentication Pipeline
1. **CSRF Middleware:** Validates `X-CSRFToken` on all non-safe HTTP methods (POST, PUT, PATCH, DELETE).
2. **Session Authentication:** Secure HTTP-only cookies protect user credentials.
3. **Role-Based Permissions:** Members can view only their assigned tasks and update task status or checklist completion on those tasks. Administrators manage task details, checklist content/order, projects, and labels.

### 2.3 Application & Business Logic
- **`accounts` App:**
  - Custom `User` model extending `AbstractUser`.
  - Roles: `ADMIN` and `MEMBER`.
  - Department, job title, and avatar initials generation.
- **`tasks` App:**
  - Manages `Task`, optional `Project`, reusable `Label`, ordered `TaskChecklistItem`, `TaskActivityLog`, and `TaskComment`.
  - Task list and Kanban queries prefetch labels, checklist items, and comments and select the optional project to avoid per-task relationship queries.
  - Automatic overdue tagging via model properties and database query annotators.
  - Dispatches notifications on assignment and status progression.
- **`notifications` App:**
  - Tracks user-targeted events, read/unread states, and direct URLs.
- **`api` App:**
  - DRF Serializers, ModelViewSets, and granular custom action endpoints.
- **Local MCP integration (`mcp_server`):**
  - Official MCP Python SDK server, launched as a local stdio subprocess; it does not expose a network listener.
  - Resolves the active user configured by `TASKFLOW_MCP_USER` on every tool call, then applies TaskFlow task visibility and role rules.
  - Runs synchronous Django ORM operations through `sync_to_async` and uses the existing task form, status serializer, and notification service.

See [MCP integration](./mcp.md) for client configuration, tool permissions, and tested behavior.

---

## 3. Data Flow Workflows

### 3.1 Kanban Status Change Flow
```mermaid
sequenceDiagram
    autonumber
    actor User as User (Drag Card)
    participant UI as Kanban UI (SortableJS)
    participant API as /api/tasks/{id}/update-status/
    participant Guard as RBAC & CSRF Validator
    participant ORM as Django ORM
    participant DB as SQLite Database
    participant Notif as Notification Service

    User->>UI: Drags task card from "To Do" to "In Progress"
    UI->>API: PATCH { status: "IN_PROGRESS" } with X-CSRFToken
    API->>Guard: Verify authentication & permissions
    Guard-->>API: Authorized
    API->>ORM: Task.objects.get(pk=id).status = "IN_PROGRESS"
    ORM->>DB: UPDATE tasks_task SET status='IN_PROGRESS', updated_at=NOW()
    DB-->>ORM: Success
    API->>Notif: Dispatch status change event to creator/assignee
    API-->>UI: 200 OK { id, status: "IN_PROGRESS", updated_at }
    UI->>User: Displays success toast & updates column counters
```

### 3.2 Threaded Comment & Notification Flow
```mermaid
sequenceDiagram
    autonumber
    actor Contributor as Team Member
    participant UI as Task Detail Page
    participant API as /api/tasks/{id}/comments/
    participant ORM as Django ORM
    participant DB as SQLite Database
    participant Notif as Notification Service
    actor Assignee as Task Assignee

    Contributor->>UI: Submits comment reply
    UI->>API: POST { content: "...", parent_id: 12 }
    API->>ORM: Create TaskComment(task, author, content, parent)
    ORM->>DB: INSERT INTO tasks_taskcomment
    DB-->>ORM: Created
    API->>Notif: Create Notification for Assignee/Owner
    Notif->>DB: INSERT INTO notifications_notification
    API-->>UI: 201 Created (Comment JSON)
    UI->>Contributor: Appends comment card to conversation thread
    Notif-->>Assignee: Bell badge increments in real-time
```
