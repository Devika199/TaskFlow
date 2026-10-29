# TaskFlow Enterprise — Deployment & Operations Guide

This runbook documents operational procedures, environment configurations, containerization, scheduled job execution, database transition (SQLite to PostgreSQL), and backup/restore workflows for TaskFlow Enterprise.

---

## 1. Environment Configuration

TaskFlow uses environment variables for operational configuration. A template is provided in [`.env.example`](file:///c:/Users/hp/Downloads/Taskflow_Ai/.env.example).

### Required Environment Variables (Production)

| Variable | Description | Example / Default |
| :--- | :--- | :--- |
| `DEBUG` | Disables development/debug mode. Must be set to `False` in production. | `False` |
| `SECRET_KEY` | Cryptographic key for session signing and tokens. Mandatory when `DEBUG=False`. Must **not** start with `django-insecure-`. | `64+ char random string` |
| `ALLOWED_HOSTS` | Comma-separated list of hostnames/domains the application is allowed to serve. | `taskflow.example.com,app.example.com` |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated list of origins trusted for POST requests via HTTPS. | `https://taskflow.example.com` |
| `DATABASE_URL` | Optional. Full connection string for database backend. Defaults to SQLite if omitted. | `postgresql://user:pass@host:5432/taskflow_db` |
| `SECURE_SSL_REDIRECT` | Enforces HTTPS redirection for all HTTP traffic. | `True` |
| `SECURE_HSTS_SECONDS` | HTTP Strict Transport Security duration in seconds. | `31536000` (1 year) |
| `LOG_LEVEL` | Application logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). | `INFO` |
| `GEMINI_API_KEY` | Google Gemini API key for TaskFlow AI assistant. | `AIzaSy...` |
| `ADMIN_REGISTRATION_CODE`| Secret code required to register system administrator accounts. | `random-strong-code` |

---

## 2. Containerized Deployment (Docker)

TaskFlow includes a production-ready container definition in [`Dockerfile`](file:///c:/Users/hp/Downloads/Taskflow_Ai/Dockerfile) and [`.dockerignore`](file:///c:/Users/hp/Downloads/Taskflow_Ai/.dockerignore).

### Key Container Features
- Base image: `python:3.12-slim` (minimal attack surface).
- Security: Runs under an unprivileged system user (`taskflow`, UID 1000).
- Static assets: Served directly and compressed via WhiteNoise (`CompressedManifestStaticFilesStorage`).
- WSGI server: Gunicorn with 3 concurrent workers.
- Built-in container healthcheck querying `http://localhost:8000/health/`.

### Building and Running the Image

```bash
# 1. Build the production Docker image
docker build -t taskflow:latest .

# 2. Run the container with environment file and port mapping
docker run -d \
  --name taskflow-app \
  -p 8000:8000 \
  --env-file .env \
  --restart unless-stopped \
  taskflow:latest

# 3. Check container logs
docker logs -f taskflow-app

# 4. Verify container health status
docker inspect --format='{{json .State.Health.Status}}' taskflow-app
```

---

## 3. Health Monitoring & Health Checks

TaskFlow exposes a lightweight, unauthenticated health check endpoint:

- **URL:** `GET /health/`
- **Success Response (HTTP 200):**
  ```json
  {"status": "healthy", "database": "connected"}
  ```
- **Failure Response (HTTP 503):**
  ```json
  {"status": "unhealthy", "database": "disconnected"}
  ```

This endpoint safely executes `connection.ensure_connection()` against the configured database backend without exposing server stack traces, schema details, or sensitive credentials.

---

## 4. SQLite to PostgreSQL Migration Runbook

When scaling out or transitioning from local SQLite to a managed PostgreSQL cluster, follow this zero-data-loss, reversible staging procedure:

### Step 1: Create Full Backups
```bash
# Backup the active SQLite database
copy db.sqlite3 db.sqlite3.pre_pg_migration.bak
```

### Step 2: Export Data Excluding ContentTypes and Permissions
Django's `contenttypes` and `auth.Permission` tables are auto-populated by `migrate`. To prevent foreign key collisions during `loaddata`, exclude them from the export:

```bash
python manage.py dumpdata \
  --natural-foreign \
  --natural-primary \
  --exclude contenttypes \
  --exclude auth.permission \
  --indent 2 \
  --output datadump.json
```

### Step 3: Configure Target PostgreSQL Instance
Set your PostgreSQL environment variables or `DATABASE_URL`:
```bash
# Example environment variables
export DATABASE_URL="postgresql://taskflow_user:secure_password@postgres-host:5432/taskflow_db"
```

### Step 4: Run Migrations on Clean PostgreSQL Database
```bash
python manage.py migrate
```

### Step 5: Load the Serialized Application Data
```bash
python manage.py loaddata datadump.json
```

### Step 6: Verify Database Records & Integrity
```bash
python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'taskflow_core.settings')
django.setup()
from organizations.models import Organization, OrganizationMembership
from tasks.models import Task, TaskReminderLog
from notifications.models import Notification

print('Organizations:', Organization.objects.count())
print('Memberships:', OrganizationMembership.objects.count())
print('Tasks:', Task.objects.count())
print('Notifications:', Notification.objects.count())
print('Reminder Logs:', TaskReminderLog.objects.count())
"
```

### Rollback Plan
If any step encounters an issue, simply unset `DATABASE_URL` (or restore SQLite configuration). The local `db.sqlite3` file and `db.sqlite3.pre_pg_migration.bak` remain completely intact.

---

## 5. Background Task Scheduling (`process_task_reminders`)

TaskFlow utilizes a database-backed idempotent reminder processor:
```bash
python manage.py process_task_reminders
```

### Scheduling on Windows (Task Scheduler)
Create a Scheduled Task running every 15 or 30 minutes:
1. Open PowerShell as Administrator.
2. Run the following command (adjust python and project paths as needed):
```powershell
$Action = New-ScheduledTaskAction -Execute "python.exe" -Argument "manage.py process_task_reminders" -WorkingDirectory "C:\Users\hp\Downloads\Taskflow_Ai"
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName "TaskFlow_Reminders" -Action $Action -Trigger $Trigger -Description "Runs TaskFlow automated due date reminders"
```

### Scheduling on Linux / Docker Hosts (Cron or Systemd Timer)
Add the following entry to crontab (`crontab -e`):
```cron
*/15 * * * * cd /app && /usr/local/bin/python manage.py process_task_reminders >> /var/log/taskflow_reminders.log 2>&1
```

Or execute via Docker:
```bash
docker exec taskflow-app python manage.py process_task_reminders
```

---

## 6. Backup & Restore Procedures

### Automated Database Backup (SQLite)
```bash
# Windows PowerShell
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item "db.sqlite3" "backups/db_$timestamp.sqlite3"

# Linux / Bash
cp db.sqlite3 "backups/db_$(date +%Y%m%d_%H%M%S).sqlite3"
```

### PostgreSQL Backup & Restore
```bash
# Dump
pg_dump -U taskflow_user -h localhost -d taskflow_db -F c -b -v -f "backups/taskflow_$(date +%Y%m%d_%H%M%S).dump"

# Restore
pg_restore -U taskflow_user -h localhost -d taskflow_db -c -v "backups/taskflow_YYYYMMDD_HHMMSS.dump"
```

