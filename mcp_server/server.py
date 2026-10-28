"""TaskFlow MCP server entry point; serves tools over stdio only."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskflow_core.settings")

import django
from django.apps import apps

if not apps.ready:
    django.setup()

from asgiref.sync import sync_to_async
from mcp.server import MCPServer

from . import tools as task_tools
from .tools import TaskDetails, TaskListResult, TaskMutationResult, TaskSummary

server = MCPServer(
    "TaskFlow",
    instructions=(
        "Work with TaskFlow tasks as the active user configured by TASKFLOW_MCP_USER. "
        "Task visibility and write permissions follow TaskFlow roles."
    ),
)


@server.tool()
async def list_my_tasks(status: str | None = None, limit: int = 50) -> TaskListResult:
    """List tasks assigned to the configured TaskFlow user, optionally by status."""
    return await sync_to_async(task_tools.list_my_tasks, thread_sensitive=True)(status, limit)


@server.tool()
async def get_task_details(task_id: int) -> TaskDetails:
    """Get a visible task, recent activity, and comments; hidden tasks are not found."""
    return await sync_to_async(task_tools.get_task_details, thread_sensitive=True)(task_id)


@server.tool()
async def list_overdue_tasks(limit: int = 50) -> TaskListResult:
    """List visible tasks whose due dates have passed and are not completed."""
    return await sync_to_async(task_tools.list_overdue_tasks, thread_sensitive=True)(limit)


@server.tool()
async def get_task_summary() -> TaskSummary:
    """Summarize tasks in the configured user's permitted scope."""
    return await sync_to_async(task_tools.get_task_summary, thread_sensitive=True)()


@server.tool()
async def create_task(
    title: str,
    description: str = "",
    status: str = "TODO",
    priority: str = "MEDIUM",
    due_date: str | None = None,
    assignee_username: str | None = None,
) -> TaskMutationResult:
    """Create a validated task as an administrator; due_date uses YYYY-MM-DD."""
    return await sync_to_async(task_tools.create_task, thread_sensitive=True)(
        title,
        description,
        status,
        priority,
        due_date,
        assignee_username,
    )


@server.tool()
async def update_task_status(task_id: int, status: str) -> TaskMutationResult:
    """Change only a visible task's status; members may update their own tasks."""
    return await sync_to_async(task_tools.update_task_status, thread_sensitive=True)(
        task_id,
        status,
    )


@server.tool()
async def assign_task(task_id: int, assignee_username: str) -> TaskMutationResult:
    """Assign a visible task to an active user; administrators only."""
    return await sync_to_async(task_tools.assign_task, thread_sensitive=True)(
        task_id,
        assignee_username,
    )


if __name__ == "__main__":
    server.run(transport="stdio")
