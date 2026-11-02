"""Microsoft To Do task operations using a Studio-resolved Microsoft Graph token."""

from typing import Any
from urllib.parse import quote

from limescape_plugin_sdk import NodeContext, NodeInput, NodeInputError

GRAPH = "https://graph.microsoft.com/v1.0"
CREDENTIAL_TYPE = "REPLACE_WITH_STUDIO_MICROSOFT_GRAPH_CREDENTIAL_TYPE"
TOKEN_FIELD = "REPLACE_WITH_STUDIO_ACCESS_TOKEN_FIELD"


def _p(inp: NodeInput, name: str, default: Any = None):
    value = inp.input_data.get(name)
    return value if value is not None and value != "" else inp.param(name, default)


def _seg(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value in {".", ".."}:
        raise NodeInputError(f"{label} is required")
    return quote(value.strip(), safe="")


async def execute(ctx: NodeContext, inp: NodeInput):
    try:
        mode, ref = _p(inp, "credential_mode", "team"), _p(inp, "credential_code")
        if mode not in {"team", "personal"} or not isinstance(ref, str) or not ref.strip():
            raise NodeInputError("Select a valid Studio Microsoft Graph credential")
        credential = await ctx.credentials.resolve(ref.strip(), mode=mode, expected_type=CREDENTIAL_TYPE)
        token = credential.values.get(TOKEN_FIELD)
        if not isinstance(token, str) or not token.strip():
            raise NodeInputError("Selected credential has no usable Microsoft Graph access token")
        action = _p(inp, "action", "list_tasks")
        list_id = _p(inp, "task_list_id")
        root = f"{GRAPH}/me/todo/lists/{_seg(list_id, 'task_list_id')}"
        task_id = _p(inp, "task_id")
        method, url, body = "GET", "", None
        if action == "list_tasks":
            url = root + "/tasks"
        elif action == "get_task":
            url = f"{root}/tasks/{_seg(task_id, 'task_id')}"
        elif action == "create_task":
            body = _p(inp, "task")
            if not isinstance(body, dict) or not isinstance(body.get("title"), str) or not body["title"].strip():
                raise NodeInputError("task must be a JSON object with a non-empty title")
            url, method = root + "/tasks", "POST"
        elif action == "update_task":
            body = _p(inp, "task")
            if not isinstance(body, dict) or not body:
                raise NodeInputError("task must be a non-empty JSON object")
            allowed = {"title", "body", "dueDateTime", "status", "importance", "reminderDateTime", "categories"}
            if set(body) - allowed:
                raise NodeInputError("task contains unsupported writable properties")
            url, method = f"{root}/tasks/{_seg(task_id, 'task_id')}", "PATCH"
        else:
            raise NodeInputError("Unsupported Microsoft To Do action")
        response = await ctx.http.request(method, url, headers={"Authorization": f"Bearer {token}"}, json=body, timeout=30)
        if not 200 <= response.status < 300:
            raise NodeInputError(f"Microsoft Graph returned HTTP {response.status}; check permissions and inputs")
        result = response.json() if response.body else {"status": response.status}
        ctx.trace.event("microsoft_todo", {"action": action, "status": "success"})
        yield {inp.output_key: {"action": action, "result": result}}
    except NodeInputError as exc:
        yield {inp.output_key: {"error": str(exc)}}
    except Exception:
        yield {inp.output_key: {"error": "Microsoft Graph credential or request failed"}}
