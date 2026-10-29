import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client as DjangoClient, TestCase
from django.urls import reverse
from google.genai import errors, types
from asgiref.sync import async_to_sync
from mcp import Client as MCPClient
from mcp_server.server import server
from tasks.models import Task

from . import services

User = get_user_model()


class FakeMcpClient:
    def __init__(self, parameters, calls=None):
        self.parameters = parameters
        self.calls = calls if calls is not None else []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    async def list_tools(self):
        tools = [
            SimpleNamespace(
                name=name,
                description=f"{name} description",
                input_schema={"type": "object", "properties": {}},
            )
            for name in sorted(services.SUPPORTED_TOOLS)
        ]
        return SimpleNamespace(tools=tools)

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return SimpleNamespace(
            is_error=False,
            structured_content={"tool": name, "arguments": arguments},
            content=[],
        )


class FakeGeminiClient:
    def __init__(self, responses):
        self.requests = []

        def generate(**kwargs):
            self.requests.append(kwargs)
            return responses.pop(0)

        self.models = SimpleNamespace(
            generate_content=generate
        )
        self.closed = False

    def close(self):
        self.closed = True


def _function_call_response(name, arguments):
    call = types.FunctionCall(name=name, args=arguments)
    content = types.Content(
        role="model",
        parts=[types.Part(function_call=call)],
    )
    return SimpleNamespace(
        function_calls=[call],
        candidates=[SimpleNamespace(content=content)],
        text=None,
    )


def _text_response(text):
    return SimpleNamespace(function_calls=None, candidates=[], text=text)


class AssistantServiceTests(TestCase):
    def test_chat_refuses_to_run_without_gemini_api_key(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            with self.assertRaisesRegex(
                services.AssistantServiceError,
                "API key is not configured",
            ):
                services.run_chat_turn("member-one", [], "Hello")

    def test_existing_mcp_server_exposes_all_tools_as_gemini_functions(self):
        async def list_tools():
            async with MCPClient(server) as client:
                return await client.list_tools()

        result = async_to_sync(list_tools)()
        google_tools = services._gemini_tools(result.tools)
        function_names = {
            declaration.name
            for declaration in google_tools[0].function_declarations
        }
        self.assertEqual(function_names, services.SUPPORTED_TOOLS)

    def test_chat_call_uses_real_mcp_tool_and_member_data_scope(self):
        member = User.objects.create_user(
            username="assistant_mcp_member",
            password="test-password",
            role=User.ROLE_MEMBER,
        )
        other_member = User.objects.create_user(
            username="assistant_mcp_other",
            password="test-password",
            role=User.ROLE_MEMBER,
        )
        Task.objects.create(
            title="Member task",
            created_by=member,
            assigned_to=member,
        )
        Task.objects.create(
            title="Other member private task",
            created_by=other_member,
            assigned_to=other_member,
        )

        gemini = FakeGeminiClient([
            _function_call_response("get_task_summary", {}),
            _text_response("You have one task."),
        ])

        def in_process_client(parameters):
            self.assertEqual(
                parameters.env["TASKFLOW_MCP_USER"],
                member.username,
            )
            return MCPClient(server)

        with (
            patch.dict(os.environ, {
                "GEMINI_API_KEY": "test-key",
                "TASKFLOW_MCP_USER": member.username,
            }),
            patch("ai_assistant.services.Client", side_effect=in_process_client),
            patch("ai_assistant.services.genai.Client", return_value=gemini),
        ):
            result = services.run_chat_turn(
                member.username,
                [],
                "Summarize my tasks",
            )

        self.assertEqual(result["text"], "You have one task.")
        tool_response = gemini.requests[1]["contents"][-1].parts[0].function_response
        self.assertEqual(tool_response.response["total"], 1)
        self.assertEqual(tool_response.response["scope"], "assigned_to_me")
        self.assertNotIn("Other member private task", str(tool_response.response))

    def test_chat_calls_a_read_only_mcp_tool_as_the_given_user(self):
        mcp_calls = []
        mcp_sessions = []

        def fake_mcp_factory(parameters):
            session = FakeMcpClient(parameters, mcp_calls)
            mcp_sessions.append(session)
            return session

        gemini = FakeGeminiClient([
            _function_call_response("get_task_summary", {}),
            _text_response("You have one task."),
        ])

        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
            patch("ai_assistant.services.Client", side_effect=fake_mcp_factory),
            patch("ai_assistant.services.genai.Client", return_value=gemini),
        ):
            result = services.run_chat_turn("member-one", [], "Summarize my tasks")

        self.assertEqual(result, {"status": "complete", "text": "You have one task."})
        self.assertEqual(mcp_calls, [("get_task_summary", {})])
        self.assertEqual(
            mcp_sessions[0].parameters.env["TASKFLOW_MCP_USER"],
            "member-one",
        )
        self.assertEqual(mcp_sessions[0].parameters.command, sys.executable)
        self.assertEqual(mcp_sessions[0].parameters.args, ["-m", "mcp_server.server"])
        self.assertEqual(mcp_sessions[0].parameters.cwd, services.settings.BASE_DIR)
        self.assertTrue(gemini.closed)

    def test_write_mcp_tool_waits_for_confirmation_then_executes(self):
        mcp_calls = []
        fake_mcp = FakeMcpClient(None, mcp_calls)
        arguments = {"title": "Approved task"}
        first_gemini = FakeGeminiClient([
            _function_call_response("create_task", arguments),
        ])
        final_gemini = FakeGeminiClient([
            _text_response("The task was created."),
        ])

        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
            patch(
                "ai_assistant.services.Client",
                return_value=fake_mcp,
            ),
            patch(
                "ai_assistant.services.genai.Client",
                side_effect=[first_gemini, final_gemini],
            ),
        ):
            proposed = services.run_chat_turn("member-one", [], "Create a task")
            self.assertEqual(proposed["status"], "confirmation_required")
            self.assertEqual(mcp_calls, [])

            completed = services.continue_chat_turn(
                "member-one",
                proposed["pending"],
                approved=True,
            )

        self.assertEqual(completed["text"], "The task was created.")
        self.assertEqual(mcp_calls, [("create_task", arguments)])
        self.assertTrue(first_gemini.closed)
        self.assertTrue(final_gemini.closed)

    def test_declining_a_write_never_calls_the_mcp_tool(self):
        gemini = FakeGeminiClient([
            _function_call_response("update_task_status", {
                "task_id": 41,
                "status": "COMPLETED",
            }),
        ])
        mcp_calls = []
        fake_mcp = FakeMcpClient(None, mcp_calls)
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
            patch("ai_assistant.services.Client", return_value=fake_mcp),
            patch("ai_assistant.services.genai.Client", return_value=gemini),
        ):
            proposed = services.run_chat_turn("member-one", [], "Complete my task")
            cancelled = services.continue_chat_turn(
                "member-one",
                proposed["pending"],
                approved=False,
            )
        self.assertEqual(cancelled["status"], "complete")
        self.assertEqual(mcp_calls, [])

    def test_default_model_is_gemini_3_5_flash(self):
        with patch.dict(os.environ, {"GEMINI_MODEL": ""}, clear=False):
            self.assertEqual(services._model_name(), "gemini-3.5-flash")

    def test_transient_503_error_retries_and_succeeds(self):
        fake_mcp = FakeMcpClient(None, [])
        error_503 = errors.APIError(
            503,
            {"error": {"code": 503, "message": "503 UNAVAILABLE: This model is currently experiencing high demand."}},
        )
        success_response = _text_response("Resolved after retry.")
        call_count = 0

        def flaky_generate(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise error_503
            return success_response

        fake_gemini = FakeGeminiClient([])
        fake_gemini.models.generate_content = flaky_generate

        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
            patch("ai_assistant.services.Client", return_value=fake_mcp),
            patch("ai_assistant.services.genai.Client", return_value=fake_gemini),
            patch("ai_assistant.services.INITIAL_RETRY_DELAY", 0.001),
        ):
            result = services.run_chat_turn("member-one", [], "Hello")

        self.assertEqual(result, {"status": "complete", "text": "Resolved after retry."})
        self.assertEqual(call_count, 2)

    def test_transient_503_error_exhausted_retries_returns_friendly_message(self):
        fake_mcp = FakeMcpClient(None, [])
        error_503 = errors.APIError(
            503,
            {"error": {"code": 503, "message": "503 UNAVAILABLE: This model is currently experiencing high demand."}},
        )
        fake_gemini = FakeGeminiClient([])
        fake_gemini.models.generate_content = lambda **kwargs: (_ for _ in ()).throw(error_503)

        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
            patch("ai_assistant.services.Client", return_value=fake_mcp),
            patch("ai_assistant.services.genai.Client", return_value=fake_gemini),
            patch("ai_assistant.services.INITIAL_RETRY_DELAY", 0.001),
        ):
            with self.assertRaises(services.AssistantServiceError) as ctx:
                services.run_chat_turn("member-one", [], "Hello")

        self.assertIn("temporarily unavailable due to high demand", str(ctx.exception))

    def test_gemini_api_error_is_wrapped_gracefully(self):
        fake_mcp = FakeMcpClient(None, [])
        fake_error = errors.APIError(
            404,
            {"error": {"message": "This model models/gemini-2.5-flash is no longer available to new users."}},
        )
        fake_gemini = FakeGeminiClient([])

        def throw_api_error(**kwargs):
            raise fake_error

        fake_gemini.models.generate_content = throw_api_error

        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
            patch("ai_assistant.services.Client", return_value=fake_mcp),
            patch("ai_assistant.services.genai.Client", return_value=fake_gemini),
        ):
            with self.assertRaises(services.AssistantServiceError) as ctx:
                services.run_chat_turn("member-one", [], "Hello")
            self.assertIn("no longer available", str(ctx.exception))

    def test_successful_multi_step_tool_calls(self):
        mcp_calls = []
        fake_mcp = FakeMcpClient(None, mcp_calls)
        gemini = FakeGeminiClient([
            _function_call_response("get_project_summary", {"project_id": 1}),
            _function_call_response("list_my_tasks", {"status": "IN_PROGRESS"}),
            _function_call_response("get_task_details", {"task_id": 10}),
            _text_response("Multi-step inspection complete."),
        ])

        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
            patch("ai_assistant.services.Client", return_value=fake_mcp),
            patch("ai_assistant.services.genai.Client", return_value=gemini),
        ):
            result = services.run_chat_turn("member-one", [], "Inspect project and tasks")

        self.assertEqual(result, {"status": "complete", "text": "Multi-step inspection complete."})
        self.assertEqual(len(mcp_calls), 3)
        self.assertEqual(mcp_calls[0][0], "get_project_summary")
        self.assertEqual(mcp_calls[1][0], "list_my_tasks")
        self.assertEqual(mcp_calls[2][0], "get_task_details")

    def test_iteration_limit_exhaustion_raises_clear_error(self):
        fake_mcp = FakeMcpClient(None, [])
        # Infinite generator of tool calls with different arguments
        round_num = 0
        def infinite_tool_calls(**kwargs):
            nonlocal round_num
            round_num += 1
            return _function_call_response("get_task_details", {"task_id": round_num})

        fake_gemini = FakeGeminiClient([])
        fake_gemini.models.generate_content = infinite_tool_calls

        with (
            patch.dict(os.environ, {
                "GEMINI_API_KEY": "test-key",
                "TASKFLOW_AI_MAX_ROUNDS": "3",
            }),
            patch("ai_assistant.services.Client", return_value=fake_mcp),
            patch("ai_assistant.services.genai.Client", return_value=fake_gemini),
        ):
            with self.assertRaises(services.AssistantServiceError) as ctx:
                services.run_chat_turn("member-one", [], "Looping request")

        err_msg = str(ctx.exception)
        self.assertIn("maximum limit of 3 tool-calling rounds", err_msg)
        self.assertIn("smaller, more specific steps", err_msg)

    def test_tool_call_limit_exhaustion_raises_clear_error(self):
        fake_mcp = FakeMcpClient(None, [])
        gemini = FakeGeminiClient([
            _function_call_response("list_my_tasks", {}),
            _function_call_response("list_overdue_tasks", {}),
            _function_call_response("get_task_summary", {}),
        ])

        with (
            patch.dict(os.environ, {
                "GEMINI_API_KEY": "test-key",
                "TASKFLOW_AI_MAX_TOOL_CALLS": "2",
            }),
            patch("ai_assistant.services.Client", return_value=fake_mcp),
            patch("ai_assistant.services.genai.Client", return_value=gemini),
        ):
            with self.assertRaises(services.AssistantServiceError) as ctx:
                services.run_chat_turn("member-one", [], "Too many tools")

        err_msg = str(ctx.exception)
        self.assertIn("limit of 2 tool calls", err_msg)
        self.assertIn("smaller, more specific steps", err_msg)

    def test_repetitive_tool_loop_is_prevented(self):
        fake_mcp = FakeMcpClient(None, [])
        # Returns identical tool call with same arguments
        gemini = FakeGeminiClient([
            _function_call_response("search_tasks", {"keyword": "stuck"}),
            _function_call_response("search_tasks", {"keyword": "stuck"}),
            _function_call_response("search_tasks", {"keyword": "stuck"}),
        ])

        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
            patch("ai_assistant.services.Client", return_value=fake_mcp),
            patch("ai_assistant.services.genai.Client", return_value=gemini),
        ):
            with self.assertRaises(services.AssistantServiceError) as ctx:
                services.run_chat_turn("member-one", [], "Stuck loop")

        err_msg = str(ctx.exception)
        self.assertIn("repetitive tool loop calling 'search_tasks'", err_msg)


class AssistantViewTests(TestCase):
    def setUp(self):
        self.member = User.objects.create_user(
            username="assistant_member",
            email="assistant_member@example.test",
            password="test-password",
            role=User.ROLE_MEMBER,
        )
        self.other_member = User.objects.create_user(
            username="assistant_other",
            email="assistant_other@example.test",
            password="test-password",
            role=User.ROLE_MEMBER,
        )
        self.chat_url = reverse("ai_assistant:chat")
        self.message_url = reverse("ai_assistant:message")

    def test_chat_page_requires_login(self):
        response = self.client.get(self.chat_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_authenticated_chat_page_renders_taskflow_chat_ui(self):
        self.client.force_login(self.member)
        response = self.client.get(self.chat_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "TaskFlow Assistant")
        self.assertContains(response, "sent to Google Gemini")

    def test_message_endpoint_requires_login(self):
        response = self.client.post(
            self.message_url,
            data='{"message":"Show my tasks"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_inactive_logged_in_user_is_refused(self):
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])
        self.client.force_login(self.member)

        with patch("ai_assistant.views.run_chat_turn") as chat:
            response = self.client.post(
                self.message_url,
                data='{"message":"Show my tasks"}',
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(chat.called)

    def test_successful_chat_uses_logged_in_user_and_saves_session_history(self):
        self.client.force_login(self.member)
        with patch(
            "ai_assistant.views.run_chat_turn",
            return_value={"status": "complete", "text": "You have one task."},
        ) as chat:
            response = self.client.post(
                self.message_url,
                data='{"message":"Summarize my tasks"}',
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "status": "complete",
            "message": "You have one task.",
        })
        chat.assert_called_once_with(self.member.username, [], "Summarize my tasks")
        session = self.client.session
        self.assertEqual(
            session["taskflow_ai_chat_history"],
            [
                {"role": "user", "text": "Summarize my tasks"},
                {"role": "model", "text": "You have one task."},
            ],
        )

    def test_invalid_json_empty_message_and_oversized_message_are_rejected(self):
        self.client.force_login(self.member)
        invalid_json = self.client.post(
            self.message_url,
            data="{",
            content_type="application/json",
        )
        empty = self.client.post(
            self.message_url,
            data='{"message":"  "}',
            content_type="application/json",
        )
        too_long = self.client.post(
            self.message_url,
            data='{"message":"' + ("x" * 4001) + '"}',
            content_type="application/json",
        )
        self.assertEqual(invalid_json.status_code, 400)
        self.assertEqual(empty.status_code, 400)
        self.assertEqual(too_long.status_code, 400)

    def test_authenticated_user_confirmation_is_required_before_write_tool(self):
        self.client.force_login(self.member)
        pending = {
            "status": "confirmation_required",
            "pending": {"calls": [{"name": "create_task", "arguments": {"title": "x"}}]},
            "tool": {
                "name": "create_task",
                "arguments": {
                    "title": "x",
                    "status": "TODO",
                    "priority": "HIGH",
                    "description": "Detailed task plan",
                },
            },
        }
        with patch(
            "ai_assistant.views.run_chat_turn",
            return_value=pending,
        ), patch("ai_assistant.views.continue_chat_turn") as continue_tool:
            first = self.client.post(
                self.message_url,
                data='{"message":"Create a task"}',
                content_type="application/json",
            )
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json()["status"], "confirmation_required")
            self.assertIn("priority HIGH", first.json()["confirmation"])
            self.assertIn("Detailed task plan", first.json()["confirmation"])
            self.assertFalse(continue_tool.called)

            confirmation_id = first.json()["action_id"]
            rejected = self.client.post(
                self.message_url,
                data=json.dumps({"action_id": "wrong-id", "confirm": True}),
                content_type="application/json",
            )
            self.assertEqual(rejected.status_code, 409)
            self.assertFalse(continue_tool.called)

            continue_tool.return_value = {"status": "complete", "text": "Created."}
            confirmed = self.client.post(
                self.message_url,
                data=json.dumps({"action_id": confirmation_id, "confirm": True}),
                content_type="application/json",
            )

        self.assertEqual(confirmed.status_code, 200)
        continue_tool.assert_called_once_with(
            self.member.username,
            pending["pending"],
            True,
        )

    def test_user_change_clears_previous_user_chat_history(self):
        self.client.force_login(self.member)
        session = self.client.session
        session["taskflow_ai_chat_user"] = self.member.pk
        session["taskflow_ai_chat_history"] = [
            {"role": "user", "text": "private previous conversation"},
        ]
        session["taskflow_ai_pending"] = {
            "user_id": self.member.pk,
            "action_id": "previous-user-action",
            "state": {},
        }
        session.save()

        self.client.force_login(self.other_member)
        with patch(
            "ai_assistant.views.run_chat_turn",
            return_value={"status": "complete", "text": "Ready."},
        ) as chat:
            response = self.client.post(
                self.message_url,
                data='{"message":"Hello"}',
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        chat.assert_called_once_with(self.other_member.username, [], "Hello")

    def test_csrf_is_required_for_chat_post(self):
        csrf_client = DjangoClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.member)
        response = csrf_client.post(
            self.message_url,
            data='{"message":"Hello"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_gemini_api_error_returns_clean_502_error_instead_of_500(self):
        self.client.force_login(self.member)
        with patch(
            "ai_assistant.views.run_chat_turn",
            side_effect=services.AssistantServiceError(
                "Gemini API error: This model models/gemini-2.5-flash is no longer available to new users."
            ),
        ):
            response = self.client.post(
                self.message_url,
                data='{"message":"Summarize tasks"}',
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 502)
            self.assertIn("no longer available", response.json()["error"])

    def test_unexpected_error_returns_clean_502_error_instead_of_500(self):
        self.client.force_login(self.member)
        with patch(
            "ai_assistant.views.run_chat_turn",
            side_effect=RuntimeError("Unexpected network failure"),
        ):
            response = self.client.post(
                self.message_url,
                data='{"message":"Summarize tasks"}',
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 502)
            self.assertIn("error", response.json())
