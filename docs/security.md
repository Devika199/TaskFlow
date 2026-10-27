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
| View System Dashboard & Team Tasks | Yes | Yes |
| Create New Task | Yes | Yes |
| Edit Assigned Task (Status, Notes) | Yes | Yes |
| Edit Any Task (Assignment, Due Date) | Only if Creator | Yes |
| Delete Task | Only if Creator | Yes |
| Drag-and-Drop Kanban Status Update | Yes (for allowed tasks) | Yes (all tasks) |
| Post Comments / Replies | Yes | Yes |
| Delete Comments | Only own comments | Any comment |
| Manage User Accounts & View Workload | No (403 Forbidden) | Yes |
| Mark Notifications as Read | Own notifications only | Own notifications only |

Object-level permission checks are verified inside ViewSets (`IsTaskOwnerOrAssigneeOrAdmin`, `IsCommentAuthorOrAdmin`).

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
