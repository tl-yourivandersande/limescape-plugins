"""SharePoint List item operations using a Studio-resolved Microsoft Graph token."""

from typing import Any
from urllib.parse import quote, urlsplit

from limescape_plugin_sdk import NodeContext, NodeInput, NodeInputError

GRAPH = "https://graph.microsoft.com/v1.0"
# TODO(integration): replace these two placeholders with the exact Studio credential contract.
CREDENTIAL_TYPE = "REPLACE_WITH_STUDIO_MICROSOFT_GRAPH_CREDENTIAL_TYPE"
TOKEN_FIELD = "REPLACE_WITH_STUDIO_ACCESS_TOKEN_FIELD"


def _param(inp: NodeInput, name: str, default: Any = None) -> Any:
    value = inp.input_data.get(name)
    return value if value is not None and value != "" else inp.param(name, default)


def _segment(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value in {".", ".."}:
        raise NodeInputError(f"{label} is required")
    return quote(value.strip(), safe="")


async def _request(ctx: NodeContext, method: str, url: str, token: str, *, json: Any = None):
    response = await ctx.http.request(method, url, headers={"Authorization": f"Bearer {token}"}, json=json, timeout=30)
    if not 200 <= response.status < 300:
        raise NodeInputError(f"Microsoft Graph returned HTTP {response.status}; check permissions and inputs")
    if response.status == 204 or not response.body:
        return {"status": response.status}
    try:
        return response.json()
    except ValueError as exc:
        raise NodeInputError("Microsoft Graph returned invalid JSON") from exc


async def execute(ctx: NodeContext, inp: NodeInput):
    try:
        mode = _param(inp, "credential_mode", "team")
        if mode not in {"team", "personal"}:
            raise NodeInputError("Credential mode must be team or personal")
        reference = _param(inp, "credential_code")
        if not isinstance(reference, str) or not reference.strip():
            raise NodeInputError("Select a Studio Microsoft Graph credential")
        credential = await ctx.credentials.resolve(
            reference.strip(), mode=mode, expected_type=CREDENTIAL_TYPE
        )
        token = credential.values.get(TOKEN_FIELD)
        if not isinstance(token, str) or not token.strip():
            raise NodeInputError("Selected credential has no usable Microsoft Graph access token")

        site = _segment(_param(inp, "site_id"), "site_id")
        list_id = _segment(_param(inp, "list_id"), "list_id")
        action = _param(inp, "action", "list_items")
        base = f"{GRAPH}/sites/{site}/lists/{list_id}/items"
        item_id = _param(inp, "item_id")
        if action == "list_items":
            url = base + "?$expand=fields"
            method, body = "GET", None
        elif action == "get_item":
            url = f"{base}/{_segment(item_id, 'item_id')}?$expand=fields"
            method, body = "GET", None
        elif action == "create_item":
            fields = _param(inp, "fields")
            if not isinstance(fields, dict) or not fields:
                raise NodeInputError("fields must be a non-empty JSON object")
            url, method, body = base, "POST", {"fields": fields}
        elif action == "update_item":
            fields = _param(inp, "fields")
            if not isinstance(fields, dict) or not fields:
                raise NodeInputError("fields must be a non-empty JSON object")
            url = f"{base}/{_segment(item_id, 'item_id')}/fields"
            method, body = "PATCH", fields
        else:
            raise NodeInputError("Unsupported Lists action")

        result = await _request(ctx, method, url, token, json=body)
        ctx.trace.event("sharepoint_list", {"action": action, "status": "success"})
        yield {inp.output_key: {"action": action, "result": result}}
    except NodeInputError as exc:
        yield {inp.output_key: {"error": str(exc)}}
    except Exception:
        # Capability errors may include sensitive provider detail; never expose it.
        yield {inp.output_key: {"error": "Microsoft Graph credential or request failed"}}
