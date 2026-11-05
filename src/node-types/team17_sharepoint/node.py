"""SharePoint sites, Lists and document libraries using a Studio-resolved Microsoft Graph token."""

import json
import re
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from limescape_plugin_sdk import HttpResponse, NodeContext, NodeInput, NodeInputError

GRAPH = "https://graph.microsoft.com/v1.0"
# TODO(integration): replace these two placeholders with the exact Studio credential contract.
CREDENTIAL_TYPE = "REPLACE_WITH_STUDIO_MICROSOFT_GRAPH_CREDENTIAL_TYPE"
TOKEN_FIELD = "REPLACE_WITH_STUDIO_ACCESS_TOKEN_FIELD"
MAX_TEXT_BYTES = 1_000_000
MAX_PAGES = 10
DEFAULT_MAX_ITEMS = 100
MAX_ITEMS_LIMIT = 1000
# Graph error codes such as "itemNotFound" are safe to return; error messages are not.
ERROR_CODE = re.compile(r"[A-Za-z][A-Za-z0-9_.]{0,63}")

SITE_ACTIONS = {"search_sites", "get_site", "list_lists", "list_drives"}
LIST_ACTIONS = {"list_items", "get_item", "create_item", "update_item", "delete_item"}
DRIVE_ACTIONS = {
    "list_files", "search_files", "get_file", "download_text", "upload_text", "create_folder", "delete_file",
}


def _param(inp: NodeInput, name: str, default: Any = None) -> Any:
    value = inp.input_data.get(name)
    return value if value is not None and value != "" else inp.param(name, default)


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NodeInputError(f"{label} is required")
    return value.strip()


def _segment(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value in {".", ".."}:
        raise NodeInputError(f"{label} is required")
    return quote(value.strip(), safe="")


def _path_parts(value: Any, label: str) -> list[str]:
    parts = [part.strip() for part in _text(value, label).split("/") if part.strip()]
    if not parts or any(part in {".", ".."} for part in parts):
        raise NodeInputError(f"{label} must be a folder or file path inside the library")
    return parts


def _encode_path(parts: list[str]) -> str:
    return "/".join(quote(part, safe="") for part in parts)


def _site_path(value: Any) -> str:
    url = urlsplit(_text(value, "site_url"))
    if url.scheme != "https" or not url.hostname:
        raise NodeInputError("site_url must be an https SharePoint site URL")
    parts = [unquote(part) for part in url.path.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise NodeInputError("site_url must be an https SharePoint site URL")
    host = quote(url.hostname, safe="")
    return f"{host}:/{_encode_path(parts)}" if parts else host


def _max_items(inp: NodeInput) -> int:
    value = _param(inp, "max_items", DEFAULT_MAX_ITEMS)
    try:
        count = DEFAULT_MAX_ITEMS if value in (None, "") else int(value)
    except (TypeError, ValueError) as exc:
        raise NodeInputError("max_items must be a whole number") from exc
    if not 1 <= count <= MAX_ITEMS_LIMIT:
        raise NodeInputError(f"max_items must be between 1 and {MAX_ITEMS_LIMIT}")
    return count


def _fields(inp: NodeInput) -> dict[str, Any]:
    fields = _param(inp, "fields")
    if isinstance(fields, str):
        try:
            fields = json.loads(fields)
        except ValueError as exc:
            raise NodeInputError("fields must be a non-empty JSON object") from exc
    if not isinstance(fields, dict) or not fields:
        raise NodeInputError("fields must be a non-empty JSON object")
    return fields


def _graph_error(response: HttpResponse) -> str:
    try:
        code = response.json()["error"]["code"]
    except (ValueError, KeyError, TypeError):
        code = None
    detail = f" ({code})" if isinstance(code, str) and ERROR_CODE.fullmatch(code) else ""
    return f"Microsoft Graph returned HTTP {response.status}{detail}; check permissions and inputs"


async def _request(
    ctx: NodeContext, method: str, url: str, token: str, *,
    body: Any = None, data: bytes | None = None, content_type: str | None = None, timeout: int = 30,
) -> HttpResponse:
    headers = {"Authorization": f"Bearer {token}"}
    if content_type:
        headers["Content-Type"] = content_type
    response = await ctx.http.request(method, url, headers=headers, json=body, data=data, timeout=timeout)
    if not 200 <= response.status < 300:
        raise NodeInputError(_graph_error(response))
    return response


def _json(response: HttpResponse) -> Any:
    if response.status == 204 or not response.body:
        return {"status": response.status}
    try:
        return response.json()
    except ValueError as exc:
        raise NodeInputError("Microsoft Graph returned invalid JSON") from exc


async def _call(ctx: NodeContext, method: str, url: str, token: str, **kwargs: Any) -> Any:
    return _json(await _request(ctx, method, url, token, **kwargs))


async def _collect(ctx: NodeContext, url: str, token: str, max_items: int) -> dict[str, Any]:
    items: list[Any] = []
    more = False
    for _ in range(MAX_PAGES):
        page = await _call(ctx, "GET", url, token)
        values = page.get("value") if isinstance(page, dict) else None
        if not isinstance(values, list):
            raise NodeInputError("Microsoft Graph returned an unexpected list response")
        items.extend(values)
        next_link = page.get("@odata.nextLink")
        more = isinstance(next_link, str)
        if len(items) >= max_items or not more:
            break
        # The token goes along with the next request, so only follow links back to Graph.
        if not next_link.startswith(GRAPH + "/"):
            raise NodeInputError("Microsoft Graph returned an unexpected next page link")
        url = next_link
    return {"value": items[:max_items], "truncated": more or len(items) > max_items}


async def _site_action(ctx: NodeContext, inp: NodeInput, action: str, token: str) -> Any:
    if action == "search_sites":
        query = quote(_text(_param(inp, "query"), "query"), safe="")
        return await _collect(ctx, f"{GRAPH}/sites?search={query}", token, _max_items(inp))
    if action == "get_site":
        return await _call(ctx, "GET", f"{GRAPH}/sites/{_site_path(_param(inp, 'site_url'))}", token)
    site = f"{GRAPH}/sites/{_segment(_param(inp, 'site_id'), 'site_id')}"
    return await _collect(ctx, site + ("/lists" if action == "list_lists" else "/drives"), token, _max_items(inp))


async def _list_action(ctx: NodeContext, inp: NodeInput, action: str, items: str, token: str) -> Any:
    if action == "list_items":
        return await _collect(ctx, items + "?$expand=fields", token, _max_items(inp))
    if action == "create_item":
        return await _call(ctx, "POST", items, token, body={"fields": _fields(inp)})
    item = f"{items}/{_segment(_param(inp, 'item_id'), 'item_id')}"
    if action == "get_item":
        return await _call(ctx, "GET", item + "?$expand=fields", token)
    if action == "update_item":
        return await _call(ctx, "PATCH", item + "/fields", token, body=_fields(inp))
    return await _call(ctx, "DELETE", item, token)


async def _drive_action(ctx: NodeContext, inp: NodeInput, action: str, drive: str, token: str) -> Any:
    path = _param(inp, "path")
    if action == "list_files":
        has_folder = isinstance(path, str) and path.strip("/ ")
        folder = f"{drive}/root:/{_encode_path(_path_parts(path, 'path'))}:" if has_folder else f"{drive}/root"
        return await _collect(ctx, folder + "/children", token, _max_items(inp))
    if action == "search_files":
        # OData string literals escape a single quote by doubling it.
        query = quote(_text(_param(inp, "query"), "query").replace("'", "''"), safe="")
        return await _collect(ctx, f"{drive}/root/search(q='{query}')", token, _max_items(inp))
    if action == "upload_text":
        parts, content = _path_parts(path, "path"), _param(inp, "content")
        if not isinstance(content, str):
            raise NodeInputError("content must be text")
        data = content.encode("utf-8")
        if len(data) > MAX_TEXT_BYTES:
            raise NodeInputError("Text content exceeds the 1 MB limit")
        return await _call(
            ctx, "PUT", f"{drive}/root:/{_encode_path(parts)}:/content", token,
            data=data, content_type="text/plain; charset=utf-8", timeout=60,
        )
    if action == "create_folder":
        *parent, name = _path_parts(path, "path")
        children = f"{drive}/root:/{_encode_path(parent)}:/children" if parent else f"{drive}/root/children"
        body = {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}
        return await _call(ctx, "POST", children, token, body=body)
    item = f"{drive}/items/{_segment(_param(inp, 'item_id'), 'item_id')}"
    if action == "get_file":
        return await _call(ctx, "GET", item, token)
    if action == "delete_file":
        return await _call(ctx, "DELETE", item, token)
    response = await _request(ctx, "GET", item + "/content", token, timeout=60)
    if len(response.body) > MAX_TEXT_BYTES:
        raise NodeInputError("File exceeds the 1 MB text download limit")
    try:
        return response.body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NodeInputError("File is not valid UTF-8 text; binary downloads are not supported") from exc


async def execute(ctx: NodeContext, inp: NodeInput):
    try:
        action = _param(inp, "action", "list_items")
        if action not in SITE_ACTIONS | LIST_ACTIONS | DRIVE_ACTIONS:
            raise NodeInputError("Unsupported SharePoint action")
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

        if action in SITE_ACTIONS:
            result = await _site_action(ctx, inp, action, token)
        else:
            site = f"{GRAPH}/sites/{_segment(_param(inp, 'site_id'), 'site_id')}"
            if action in LIST_ACTIONS:
                items = f"{site}/lists/{_segment(_param(inp, 'list_id'), 'list_id')}/items"
                result = await _list_action(ctx, inp, action, items, token)
            else:
                drive = f"{site}/drives/{_segment(_param(inp, 'drive_id'), 'drive_id')}"
                result = await _drive_action(ctx, inp, action, drive, token)
        ctx.trace.event("sharepoint", {"action": action, "status": "success"})
        yield {inp.output_key: {"action": action, "result": result}}
    except NodeInputError as exc:
        yield {inp.output_key: {"error": str(exc)}}
    except Exception:
        # Capability errors may include sensitive provider detail; never expose it.
        yield {inp.output_key: {"error": "Microsoft Graph credential or request failed"}}
