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

## Verification

The automated tests use Django `TestCase` data and the MCP SDK client to verify
tool discovery, valid and invalid arguments, inactive/unknown configured
users, member/admin permissions, task visibility, database updates, activity
entries, and notifications. The real stdio server was also listed and called
through MCP Inspector during integration verification.
