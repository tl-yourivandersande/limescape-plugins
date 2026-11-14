"""Microsoft To Do task operations using a Studio-resolved Microsoft Graph token."""

from typing import Any
from urllib.parse import quote

from limescape_plugin_sdk import CapabilityError, NodeContext, NodeInput, NodeInputError

GRAPH = "https://graph.microsoft.com/v1.0"
# The platform's Microsoft 365 (Graph) OAuth type. With oauth2=True the platform refreshes the
# token and returns only the access token and plain fields, never the refresh token or client secret.
CREDENTIAL_TYPE = "microsoft365OAuth2Api"
TOKEN_FIELD = "accessToken"  # noqa: S105 - a field name, not a secret
# The credential dropdown stores a team or personal credential code, or "@user:<type>" for the
# credential of that type of whoever starts the flow (the platform's [Aanroeper] choice).
USER_PREFIX = "@user:"
# Platform refusals (CapabilityError.code) as a safe, actionable message; the platform's text is not passed on.
REFUSALS = {
    "not_found": "The selected credential does not exist or is not active in this team",
    "wrong_type": "Select a Microsoft 365 (OAuth2) credential",
    "ambiguous": "More than one credential matches the selection",
    "oauth_failed": "The Microsoft 365 credential is not authorized (any more). Authorize it again",
    "unsupported": "This platform does not support Microsoft 365 OAuth for plugins yet",
    "invalid_identity": "No user is known for this run. Select a team credential",
    "no_scope": "No team is known for this run",
}
NO_LINK = "You have no Microsoft 365 credential yet. Add one under your personal credentials"


def _p(inp: NodeInput, name: str, default: Any = None):
    value = inp.input_data.get(name)
    return value if value is not None and value != "" else inp.param(name, default)


def _seg(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value in {".", ".."}:
        raise NodeInputError(f"{label} is required")
    return quote(value.strip(), safe="")


async def _access_token(ctx: NodeContext, reference: str) -> str:
    """The Graph access token of the selected credential; the platform refreshes it and keeps the secrets.

    A code is a team credential, or else a fixed personal one that everyone who runs the flow uses
    (the deprecated credential_mode field is no longer needed). "@user:" selects the caller's own.
    """
    caller = reference.startswith(USER_PREFIX)
    try:
        if caller:
            if reference != USER_PREFIX + CREDENTIAL_TYPE:
                raise NodeInputError(REFUSALS["wrong_type"])
            credential = await ctx.credentials.resolve(
                CREDENTIAL_TYPE, mode="personal_type", expected_type=CREDENTIAL_TYPE, oauth2=True
            )
        else:
            try:
                credential = await ctx.credentials.resolve(
                    reference, mode="team", expected_type=CREDENTIAL_TYPE, oauth2=True
                )
            except CapabilityError as exc:
                if exc.code != "not_found":
                    raise
                credential = await ctx.credentials.resolve(
                    reference, mode="personal", expected_type=CREDENTIAL_TYPE, oauth2=True
                )
    except CapabilityError as exc:
        if exc.code == "not_found" and caller:
            raise NodeInputError(NO_LINK) from None
        if exc.code in REFUSALS:
            raise NodeInputError(REFUSALS[exc.code]) from None
        raise
    token = credential.values.get(TOKEN_FIELD)
    if not isinstance(token, str) or not token.strip():
        raise NodeInputError("Selected credential has no usable Microsoft Graph access token")
    return token


async def execute(ctx: NodeContext, inp: NodeInput):
    try:
        ref = _p(inp, "credential_code")
        if not isinstance(ref, str) or not ref.strip():
            raise NodeInputError("Select a Microsoft 365 (OAuth2) credential")
        token = await _access_token(ctx, ref.strip())
        action = _p(inp, "action", "list_tasks")
        if action == "list_task_lists":
            method, url, body = "GET", f"{GRAPH}/me/todo/lists", None
        else:
            list_id = _seg(_p(inp, "task_list_id"), "task_list_id")
            root = f"{GRAPH}/me/todo/lists/{list_id}"
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
