"""SharePoint document library file operations using a Studio-resolved Graph token."""

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
        site, drive = _seg(_p(inp, "site_id"), "site_id"), _seg(_p(inp, "drive_id"), "drive_id")
        action = _p(inp, "action", "list_files")
        root = f"{GRAPH}/sites/{site}/drives/{drive}"
        item = _p(inp, "item_id")
        path = _p(inp, "path")
        method, url, request_kwargs = "GET", "", {}
        if action == "list_files":
            url = root + "/root/children"
        elif action == "get_file":
            url = f"{root}/items/{_seg(item, 'item_id')}"
        elif action == "download_text":
            url = f"{root}/items/{_seg(item, 'item_id')}/content"
        elif action == "upload_text":
            if not isinstance(path, str) or not path.strip() or not isinstance(_p(inp, "content"), str):
                raise NodeInputError("path and text content are required")
            if len(_p(inp, "content")) > 1_000_000:
                raise NodeInputError("Text content exceeds the 1 MB limit")
            encoded_path = "/".join(quote(part, safe="") for part in path.strip("/").split("/"))
            url, method = f"{root}/root:/{encoded_path}:/content", "PUT"
            request_kwargs["content"] = _p(inp, "content").encode("utf-8")
            request_kwargs["headers"] = {"Content-Type": "text/plain; charset=utf-8"}
        else:
            raise NodeInputError("Unsupported document library action")
        headers = {"Authorization": f"Bearer {token}", **request_kwargs.pop("headers", {})}
        response = await ctx.http.request(method, url, headers=headers, timeout=60, **request_kwargs)
        if not 200 <= response.status < 300:
            raise NodeInputError(f"Microsoft Graph returned HTTP {response.status}; check permissions and inputs")
        if action == "download_text":
            try:
                result = response.body.decode("utf-8") if isinstance(response.body, bytes) else str(response.body)
            except UnicodeDecodeError as exc:
                raise NodeInputError("File is not valid UTF-8 text; binary downloads are not supported") from exc
        else:
            result = response.json() if response.body else {"status": response.status}
        ctx.trace.event("sharepoint_file", {"action": action, "status": "success"})
        yield {inp.output_key: {"action": action, "result": result}}
    except NodeInputError as exc:
        yield {inp.output_key: {"error": str(exc)}}
    except Exception:
        yield {inp.output_key: {"error": "Microsoft Graph credential or request failed"}}
