import json
import logging
import secrets

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .services import AssistantServiceError, _clean_error_message, continue_chat_turn, run_chat_turn

logger = logging.getLogger(__name__)

MAX_REQUEST_BYTES = 16_384
MAX_MESSAGE_LENGTH = 4_000
MAX_HISTORY_MESSAGES = 12
MAX_HISTORY_MESSAGE_LENGTH = 4_000


@login_required
@never_cache
def chat_page(request):
    return render(request, "assistant/chat.html", {
        "chat_history": _history_for_user(request),
    })


def _read_request_json(request):
    try:
        declared_length = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        return None, "Invalid request length."
    if declared_length > MAX_REQUEST_BYTES:
        return None, "Request body is too large."
    if len(request.body) > MAX_REQUEST_BYTES:
        return None, "Request body is too large."
    try:
        payload = json.loads(request.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "Request body must be valid JSON."
    if not isinstance(payload, dict):
        return None, "Request body must be a JSON object."
    return payload, None


def _valid_history(history):
    if not isinstance(history, list):
        return []
    valid = []
    for item in history[-MAX_HISTORY_MESSAGES:]:
        if (
            isinstance(item, dict)
            and item.get("role") in {"user", "model"}
            and isinstance(item.get("text"), str)
        ):
            valid.append({
                "role": item["role"],
                "text": item["text"][:MAX_HISTORY_MESSAGE_LENGTH],
            })
    return valid


def _history_for_user(request):
    if request.session.get("taskflow_ai_chat_user") != request.user.pk:
        request.session.pop("taskflow_ai_chat_history", None)
        request.session.pop("taskflow_ai_pending", None)
        request.session["taskflow_ai_chat_user"] = request.user.pk
    return _valid_history(request.session.get("taskflow_ai_chat_history", []))


def _describe_action(tool):
    name = tool.get("name")
    arguments = tool.get("arguments", {})
    if name == "create_task":
        title = arguments.get("title", "(untitled)")
        details = [
            f"status {arguments.get('status', 'TODO')}",
            f"priority {arguments.get('priority', 'MEDIUM')}",
        ]
        if arguments.get("due_date"):
            details.append(f"due {arguments['due_date']}")
        if arguments.get("assignee_username"):
            details.append(f"assigned to {arguments['assignee_username']}")
        description = arguments.get("description", "")
        if description:
            details.append(f"description “{description}”")
        return f"Create “{title}” ({', '.join(details)})?"
    if name == "update_task_status":
        return (
            f"Change task #{arguments.get('task_id')} to "
            f"{arguments.get('status')}?"
        )
    if name == "assign_task":
        return (
            f"Assign task #{arguments.get('task_id')} to "
            f"{arguments.get('assignee_username')}?"
        )
    return "Confirm this TaskFlow change?"


def _save_completed_turn(request, prior_history, message, response_text):
    history = prior_history + [
        {"role": "user", "text": message},
        {"role": "model", "text": response_text},
    ]
    request.session["taskflow_ai_chat_history"] = _valid_history(history)
    request.session.pop("taskflow_ai_pending", None)


def _pending_response(request, prior_history, message, result):
    org_slug = request.organization.slug if getattr(request, 'organization', None) else ""
    pending = {
        "action_id": secrets.token_urlsafe(24),
        "user_id": request.user.pk,
        "org": org_slug,
        "history": prior_history,
        "message": message,
        "state": result["pending"],
        "tool": result["tool"],
    }
    request.session["taskflow_ai_pending"] = pending
    return JsonResponse({
        "status": "confirmation_required",
        "action_id": pending["action_id"],
        "confirmation": _describe_action(pending["tool"]),
    })


@login_required
@require_POST
def chat_message(request):
    if not request.user.is_active:
        return JsonResponse({"error": "An active account is required."}, status=403)

    payload, error = _read_request_json(request)
    if error:
        return JsonResponse({"error": error}, status=400)

    org_slug = request.organization.slug if getattr(request, 'organization', None) else ""
    history = _history_for_user(request)
    current_pending = request.session.get("taskflow_ai_pending")
    if "action_id" in payload:
        if not isinstance(payload["action_id"], str):
            return JsonResponse({"error": "Invalid confirmation request."}, status=400)
        if not isinstance(payload.get("confirm"), bool):
            return JsonResponse({"error": "Choose whether to confirm the action."}, status=400)
        stored_action_id = (
            current_pending.get("action_id")
            if isinstance(current_pending, dict)
            else None
        )
        if (
            not isinstance(current_pending, dict)
            or current_pending.get("user_id") != request.user.pk
            or not isinstance(stored_action_id, str)
            or not secrets.compare_digest(
                stored_action_id,
                payload["action_id"],
            )
        ):
            return JsonResponse({"error": "This confirmation is no longer available."}, status=409)

        request.session.pop("taskflow_ai_pending", None)
        pending_org = current_pending.get("org") or org_slug
        continue_kwargs = {}
        if pending_org:
            continue_kwargs["organization"] = pending_org
        try:
            result = continue_chat_turn(
                request.user.get_username(),
                current_pending["state"],
                payload["confirm"],
                **continue_kwargs,
            )
        except AssistantServiceError as exc:
            logger.warning("TaskFlow assistant confirmation failed: %s", exc)
            return JsonResponse({"error": str(exc)}, status=502)
        except Exception as exc:
            logger.exception("TaskFlow assistant unexpected confirmation error: %s", exc)
            return JsonResponse({"error": f"Assistant service error: {_clean_error_message(exc)}"}, status=502)

        if result["status"] == "confirmation_required":
            return _pending_response(
                request,
                current_pending["history"],
                current_pending["message"],
                result,
            )

        _save_completed_turn(
            request,
            current_pending["history"],
            current_pending["message"],
            result["text"],
        )
        return JsonResponse({"status": "complete", "message": result["text"]})

    if current_pending:
        return JsonResponse({
            "error": "Confirm or cancel the pending action before sending another message."
        }, status=409)

    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        return JsonResponse({"error": "Enter a message."}, status=400)
    message = message.strip()
    if len(message) > MAX_MESSAGE_LENGTH:
        return JsonResponse({
            "error": f"Messages must be {MAX_MESSAGE_LENGTH} characters or fewer."
        }, status=400)

    run_kwargs = {}
    if org_slug:
        run_kwargs["organization"] = org_slug
    try:
        result = run_chat_turn(
            request.user.get_username(),
            history,
            message,
            **run_kwargs,
        )
    except AssistantServiceError as exc:
        logger.warning("TaskFlow assistant request failed: %s", exc)
        return JsonResponse({"error": str(exc)}, status=502)
    except Exception as exc:
        logger.exception("TaskFlow assistant unexpected error: %s", exc)
        return JsonResponse({"error": f"Assistant service error: {_clean_error_message(exc)}"}, status=502)

    if result["status"] == "confirmation_required":
        return _pending_response(request, history, message, result)

    _save_completed_turn(request, history, message, result["text"])
    return JsonResponse({"status": "complete", "message": result["text"]})
