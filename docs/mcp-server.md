# TaskFlow MCP server

TaskFlow exposes its task workflow through the official MCP Python SDK over
**stdio only**. The server does not bind a network port. It runs with one
configured TaskFlow username and re-reads that active user from the database
for every tool call.

## Install and run

Install the project's Python dependencies:

```powershell
python -m pip install -r requirements.txt
```

Set `TASKFLOW_MCP_USER` to an existing TaskFlow username, then start the server
from the repository root:

```powershell
$env:TASKFLOW_MCP_USER = "your-username"
python -m mcp_server.server
```

The process waits for an MCP client on stdin/stdout. Do not pipe other output
to stdout; application logs go to stderr.

## Tools

| Tool | Access and behavior |
| --- | --- |
| `list_my_tasks` | Lists tasks assigned to the configured user; accepts an optional status and a limit from 1 to 100. |
| `get_task_details` | Returns a visible task, up to 20 recent activity entries, and up to 20 recent comments. Hidden and missing tasks both return `Task not found.` |
| `list_overdue_tasks` | Lists visible, incomplete tasks past their due date. |
| `get_task_summary` | Returns counts for all tasks to admins and assigned tasks to members. |
| `create_task` | Admin only. Uses the existing `TaskForm`, status and priority choices, ISO `YYYY-MM-DD` dates, and active usernames for assignment. |
| `update_task_status` | Admins may update any task; members may update tasks assigned to them. Only the status field is changed. |
| `assign_task` | Admin only; the assignee must be an active user. |

Task creation, status changes, and assignment create the same categories of
activity entries and in-app notifications as TaskFlow's existing web/API paths.
Task descriptions are limited to 10,000 characters for MCP input. Returned task
data contains usernames rather than email addresses or other account details.
Task records include an optional project name and label names/colours. Task
details additionally include ordered checklist items; MCP does not modify
checklist items.

## Inspect with MCP Inspector

The official Inspector CLI requires Node.js 22.19 or newer. Set the MCP user
explicitly for the Inspector-launched subprocess, then list the server tools:

```powershell
$env:TASKFLOW_MCP_USER = "your-username"
npx --yes @modelcontextprotocol/inspector --cli -e "TASKFLOW_MCP_USER=$env:TASKFLOW_MCP_USER" python -m mcp_server.server --method tools/list
```

To smoke-test a read-only tool:

```powershell
npx --yes @modelcontextprotocol/inspector --cli -e "TASKFLOW_MCP_USER=$env:TASKFLOW_MCP_USER" python -m mcp_server.server --method tools/call --tool-name get_task_summary
```
