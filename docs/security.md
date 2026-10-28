# TaskFlow - Security Policy & Architecture

## 1. Authentication & Identity Management
- **Password Hashing:** Django's default PBKDF2 algorithm with a SHA-256 hash and 600,000 iterations. Plain-text passwords are never logged or stored.
- **Session Security:**
  - Cookies are protected with `HttpOnly` to eliminate client-side JavaScript theft.
  - `SameSite='Lax'` prevents cross-site request forgery attacks via third-party cross-site navigation.
  - Session expiration is set to 14 days, with session renewal on privilege changes.

---

## 2. Authorization & Role-Based Access Control (RBAC)

TaskFlow implements strict server-side authorization checks on both standard Django views and DRF REST endpoints:

| Action / Capability | Member | Administrator |
| :--- | :---: | :---: |
| View tasks | Assigned tasks only | All tasks |
| Create task | No | Yes |
| Edit task details, assignee, project, or labels | No | Yes |
| Change task status | Assigned tasks only | All tasks |
| Delete task | No | Yes |
| Read checklist items | Assigned tasks only | All tasks |
| Add, edit, delete, or reorder checklist items | No | Yes |
| Complete or uncomplete checklist items | Assigned tasks only | All tasks |
| Read projects | Projects containing the member's assigned tasks only | All projects |
| Create, edit, archive, or restore projects | No | Yes |
| Read labels | Yes | Yes |
| Create, edit, or delete labels / attach labels to tasks | No | Yes |
| Post Comments / Replies | Yes | Yes |
| Delete Comments | Only own comments | Any comment |
| Manage User Accounts & View Workload | No (403 Forbidden) | Yes |
| Mark Notifications as Read | Own notifications only | Own notifications only |

These rules are enforced in Django views and API viewsets. Checklist and project lookups are scoped before object retrieval, so a member's inaccessible task, item, or project returns the same `404 Not Found` response as a missing object. A checklist completion update accepts only the completion field for members; item titles and ordering remain administrator-controlled.

### Task Calendar, Command Search, and CSV Export
- `/calendar/` applies the same task visibility boundary: members see only tasks assigned to themselves; administrators may see all tasks or filter by assignee.
- `/tasks/command-search/` requires an authenticated session and filters the database query by the current user's visible tasks before returning task matches. The browser does not use a client-supplied user identifier for identity or authorization.
- `/tasks/export.csv` is administrator-only. It reuses the task-list filters and prefixes CSV cells beginning with `=`, `+`, `-`, or `@` with a single quote to mitigate spreadsheet formula injection. The attachment name is generated from a fixed prefix and the server's local date.
- Theme preference is stored in browser `localStorage`; it is presentation-only and does not change server authorization.

---

## 3. Cross-Site Request Forgery (CSRF) Mitigation
All state-modifying requests (POST, PUT, PATCH, DELETE) require a valid CSRF token:
- In Django HTML forms: `{% csrf_token %}` hidden input tag.
- In AJAX and Fetch API calls: Extracted from `document.cookie` or the meta tag and included in the HTTP header:
  ```javascript
  headers: {
    'X-CSRFToken': getCookie('csrftoken'),
    'Content-Type': 'application/json'
  }
  ```

---

## 4. Injection & Cross-Site Scripting (XSS) Defenses
- **SQL Injection:** Exclusively avoided by using Django ORM parameterized queries. Raw SQL queries are not permitted in the codebase.
- **XSS Prevention:**
  - Django template engine auto-escapes all dynamic variables (`{{ task.title }}`).
  - User descriptions and comments are sanitized if rendered with formatting; raw HTML tags are safely stripped.
  - DRF serializers validate and sanitize JSON payloads before committing to the database.

---

## 5. Security Checklist for Production
- [x] `DEBUG = False` in production environment.
- [x] Enforce HTTPS / `SECURE_SSL_REDIRECT = True` when deployed.
- [x] `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS` enabled for SSL deployments.
- [x] `SESSION_COOKIE_SECURE = True` and `CSRF_COOKIE_SECURE = True` over HTTPS.
- [x] Content-Security-Policy (CSP) headers to restrict unauthorized script execution.

## 6. Local MCP Server
- The TaskFlow MCP server uses stdio only; it does not expose a network listener.
- `TASKFLOW_MCP_USER` selects one TaskFlow username. The active user is queried from the database for every tool call, and missing or inactive users are refused.
- MCP arguments cannot supply an acting user ID. All clients using the same server process share its configured user's permissions; this is not per-client authentication.
- Task visibility, member/admin write restrictions, and active-assignee checks are enforced by the MCP task tools. Hidden and missing task lookups return the same not-found error.
- The server can create tasks, change statuses, and assign tasks; clients or users with access to the local MCP configuration can request these writes under the configured user's role. Protect that configuration, process environment, repository, and database.
- This integration does not add remote transport, per-client identity, or an additional approval step for writes. See [MCP integration](./mcp.md) for tool-specific permissions.
