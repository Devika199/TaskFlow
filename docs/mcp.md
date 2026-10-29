# TaskFlow MCP integration

TaskFlow provides a local Model Context Protocol (MCP) server using the
official Python SDK. It communicates over **stdio only** and does not open a
network listener.

## Installation

Use the same Python environment and repository checkout as TaskFlow:

```powershell
python -m pip install -r requirements.txt
```

The requirements pin the MCP SDK to `mcp==2.3.0`. The SDK release metadata
requires Python 3.10 or later; the project was tested with Python 3.12.

## Configuration and start

Create a TaskFlow user in the application's database, then set the
`TASKFLOW_MCP_USER` environment variable to that user's **username**. Start the
server from the repository root:

```powershell
$env:TASKFLOW_MCP_USER = "your-taskflow-username"
python -m mcp_server.server
```

The server checks the configured username against the database on every tool
call and refuses missing or inactive users. Tool arguments cannot select or
override this identity. MCP protocol messages use stdin/stdout; operational
logs go to stderr.

## Connect a local client

The following examples use Windows paths. Replace the Python executable,
project directory, and username with values from your environment. Keep the
client's `cwd` set to the repository root so Django settings and the project
database are available.

### Cursor

Add a local stdio server in Cursor's MCP configuration (for example
`.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "taskflow": {
      "command": "C:\\path\\to\\python.exe",
      "args": ["-m", "mcp_server.server"],
      "cwd": "C:\\path\\to\\Taskflow_Ai",
      "env": {
        "TASKFLOW_MCP_USER": "your-taskflow-username"
      }
    }
  }
}
```

### Claude Desktop

Add an entry under `mcpServers` in Claude Desktop's `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "taskflow": {
      "command": "C:\\path\\to\\python.exe",
      "args": ["-m", "mcp_server.server"],
      "cwd": "C:\\path\\to\\Taskflow_Ai",
      "env": {
        "TASKFLOW_MCP_USER": "your-taskflow-username"
      }
    }
  }
}
```

These are configuration examples for clients that launch local stdio servers;
the MCP server and its stdio tools were exercised by the automated SDK client
test. The configuration examples themselves have not been independently
verified in Cursor or Claude Desktop.

## Tools and permissions

| Tool | Member | Administrator |
| --- | --- | --- |
| `list_my_tasks` | Lists tasks assigned to the configured user; optional status and limit (1–100). | Lists assigned tasks (same behavior). |
| `get_task_details` | Reads an assigned task, its recent activity, and comments. | Reads any task, its recent activity, and comments. |
| `list_overdue_tasks` | Lists visible, incomplete, overdue tasks. | Lists visible, incomplete, overdue tasks (all tasks). |
| `get_task_summary` | Counts assigned tasks only. | Counts all tasks. |
| `create_task` | Not allowed. | Creates a task through the existing `TaskForm`, with optional active assignee. |
| `update_task_status` | Updates status only on an assigned task. | Updates status only on any task. |
| `assign_task` | Not allowed. | Assigns a task to an active user. |
| `search_tasks` | Searches assigned tasks only. | Searches all tasks. |
| `get_project_summary` | Only projects containing at least one task assigned to the user; metrics count only those assigned tasks. | Any project; metrics count all project tasks. |
| `get_daily_briefing` | Summarizes only the configured user's assigned tasks. | Still summarizes only the configured user's assigned tasks. |
| `get_team_workload` | Not allowed. | Returns aggregate counts for active users. |

### Additional tool arguments and examples

`search_tasks` requires a non-empty `keyword` (maximum 200 characters). It
searches task titles and descriptions case-insensitively. Optional `status` and
`priority` must match the model choices. `due_date_from` and `due_date_to` are
inclusive ISO dates (`YYYY-MM-DD`), and the start must not be after the end.
`limit` is optional and must be between 1 and 100 (default 50). Results use
the same task visibility rules as the existing task tools.

```json
{
  "keyword": "release",
  "status": "IN_PROGRESS",
  "priority": "HIGH",
  "due_date_from": "2026-10-28",
  "due_date_to": "2026-11-04",
  "limit": 20
}
```

`get_project_summary` takes a positive integer `project_id`. A member receives
`Project not found.` both for a nonexistent project and for a project that has
no tasks assigned to them. Its result includes the visible project task count,
completed and in-progress counts, overdue count, and completion percentage.

```json
{"project_id": 12}
```

`get_daily_briefing` takes no arguments. It returns the configured user's
assigned tasks due today, incomplete overdue tasks, and incomplete tasks due
from tomorrow through the next seven days. It uses Django's local date
(`timezone.localdate()`) and returns task records and counts for each group.

```json
{}
```

`get_team_workload` takes no arguments and is administrator-only. It returns
the current local date and one aggregate record per active user containing
their username and assigned, completed, and overdue task counts. It does not
return task titles, descriptions, or other task details.

```json
{}
```

Statuses and priorities must match the existing TaskFlow model choices. Dates
use ISO `YYYY-MM-DD`; valid past dates are allowed and count as overdue while
the task is incomplete. Descriptions sent to task creation are capped at
10,000 characters. Hidden and nonexistent task detail/status lookups return the
same `Task not found.` error.

Task creation, status changes, and assignment write activity entries and use
the existing in-app notification service. MCP task results include usernames,
not email addresses. Task results also include the optional project name and
label names/colours; task details include ordered checklist items. Checklist
items are read-only through MCP; use the web or REST API to manage them.

## Authentication and security limitations

MCP client authentication is not a separate user login: the local server
process operates as the single TaskFlow user named by `TASKFLOW_MCP_USER`.
Every client connected to that process therefore shares that user's access.
The MCP tools do not accept a user ID or authenticate individual client
sessions.

The stdio transport is local to the launching host and has no HTTP endpoint.
Anyone able to edit or use the client configuration and launch the process can
invoke the tools with its configured identity. Protect the client config,
repository, Python environment, and database accordingly. This integration
does not add per-client identity, remote transport, or additional approval
prompts for writes. Django's model validation, role checks, and database
constraints remain in effect for the implemented task operations.

The project summary uses the same visibility rule as task lists: members see
only projects containing tasks assigned to them and receive metrics for only
those tasks. The daily briefing is personal even for administrators; it never
includes other users' assigned tasks. The team workload tool is an aggregate
view, restricted to configured administrators, and reports active users only.

## Verification

The automated tests use Django `TestCase` data and the MCP SDK client to verify
tool discovery, valid and invalid arguments, inactive/unknown configured
users, member/admin permissions, task visibility, database updates, activity
entries, and notifications. The real stdio server was also listed and called
through MCP Inspector during integration verification.

## Django Gemini assistant

The authenticated TaskFlow chat page uses the official `google-genai` Python
SDK and the existing MCP server. Install project dependencies with
`python -m pip install -r requirements.txt`, then set the Gemini API key in
the environment of the Django process. For PowerShell:

```powershell
$env:GEMINI_API_KEY = "your-key-from-Google-AI-Studio"
python manage.py runserver
```

Never put the key in templates, browser JavaScript, source control, or chat
messages. `GEMINI_MODEL` is optional; the default is `gemini-3.5-flash`.

Open **AI Assistant** from the authenticated TaskFlow sidebar. Each chat
request starts a separate stdio MCP process using the logged-in active user's
username as `TASKFLOW_MCP_USER`; it does not reuse the identity configured in
MCP Inspector. The server continues to resolve that identity from the database
and apply its existing task and role permissions. The chat endpoint is
login-required, POST-only, and CSRF-protected.

Read-only tools may be called while answering. Before the assistant executes
`create_task`, `update_task_status`, or `assign_task`, it displays the proposed
action and waits for confirmation. Pending actions and a bounded conversation
history are stored in the user's Django session; chat does not add a model or
migration.

Chat messages and tool results needed to answer them are sent to Google's
Gemini API. The page discloses this before chat use. Do not send information
that your organization does not permit sharing with that service. TaskFlow
does not send its Gemini API key to the MCP subprocess or browser.
