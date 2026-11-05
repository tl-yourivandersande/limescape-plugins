from pathlib import Path

import pytest
from limescape_plugin_sdk.testing import FakeContext, run_node

NODE_DIR = Path(__file__).resolve().parents[1]
TYPE = "REPLACE_WITH_STUDIO_MICROSOFT_GRAPH_CREDENTIAL_TYPE"
TOKEN = "synthetic-graph-token"
GRAPH = "https://graph.microsoft.com/v1.0"
SITE = f"{GRAPH}/sites/site-1"
DRIVE = f"{SITE}/drives/drive-1"


def context(*responses):
    return FakeContext(
        granted=["credentials", "http"],
        credential_resolver=lambda reference, **kwargs: {
            "reference": reference, "type_name": TYPE,
            "values": {"REPLACE_WITH_STUDIO_ACCESS_TOKEN_FIELD": TOKEN},
        },
        http_responses=list(responses),
    )


async def run(ctx, input_data=None, **params):
    params = {"credential_code": "graph-team", "site_id": "site-1", "list_id": "list-1", "drive_id": "drive-1"} | params
    result = await run_node(NODE_DIR, ctx, params=params, input_data=input_data or {}, output_key="result")
    return result[0]["result"]


def http_requests(ctx):
    return [call.request for call in ctx.calls if call.capability == "http"]


async def test_list_items_uses_fixed_graph_host_and_resolved_credential():
    """List items builds a fixed Graph endpoint and sends the resolved token."""
    ctx = context({"status": 200, "json": {"value": [{"id": "item-1"}]}})
    output = await run(ctx, action="list_items")
    assert ctx.calls[0].request["expected_type"] == TYPE
    request = http_requests(ctx)[0]
    assert request["url"] == f"{SITE}/lists/list-1/items?$expand=fields"
    assert request["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert output == {"action": "list_items", "result": {"value": [{"id": "item-1"}], "truncated": False}}


async def test_pagination_follows_graph_links_and_stops_at_max_items():
    """Next-page links are followed until max_items is reached."""
    next_link = f"{SITE}/lists?$skiptoken=abc"
    ctx = context(
        {"status": 200, "json": {"value": [{"id": "1"}, {"id": "2"}], "@odata.nextLink": next_link}},
        {"status": 200, "json": {"value": [{"id": "3"}, {"id": "4"}], "@odata.nextLink": next_link + "x"}},
    )
    output = await run(ctx, action="list_lists", max_items="3")
    assert [request["url"] for request in http_requests(ctx)] == [f"{SITE}/lists", next_link]
    assert output["result"] == {"value": [{"id": "1"}, {"id": "2"}, {"id": "3"}], "truncated": True}


async def test_pagination_never_sends_the_token_outside_graph():
    """A next-page link to another host is refused instead of followed."""
    ctx = context({"status": 200, "json": {"value": [{"id": "1"}], "@odata.nextLink": "https://evil.example/steal"}})
    output = await run(ctx, action="list_drives")
    assert output == {"error": "Microsoft Graph returned an unexpected next page link"}
    assert [request["url"] for request in http_requests(ctx)] == [f"{SITE}/drives"]


@pytest.mark.parametrize("max_items", ["0", "1001", "many"])
async def test_max_items_is_bounded(max_items):
    ctx = context()
    output = await run(ctx, action="list_items", max_items=max_items)
    assert "max_items" in output["error"]
    assert http_requests(ctx) == []


async def test_get_site_turns_url_into_graph_site_path():
    """Get site by URL needs no site ID and keeps the URL's host and path."""
    ctx = context({"status": 200, "json": {"id": "contoso.sharepoint.com,a,b"}})
    output = await run(ctx, action="get_site", site_id="", site_url="https://contoso.sharepoint.com/sites/Team%20Site")
    assert http_requests(ctx)[0]["url"] == f"{GRAPH}/sites/contoso.sharepoint.com:/sites/Team%20Site"
    assert output["result"] == {"id": "contoso.sharepoint.com,a,b"}


async def test_get_site_rejects_non_https_url():
    ctx = context()
    output = await run(ctx, action="get_site", site_url="http://contoso.sharepoint.com/sites/a")
    assert "https" in output["error"]
    assert http_requests(ctx) == []


async def test_search_sites_encodes_query():
    ctx = context({"status": 200, "json": {"value": []}})
    await run(ctx, action="search_sites", site_id="", query="sales & marketing")
    assert http_requests(ctx)[0]["url"] == f"{GRAPH}/sites?search=sales%20%26%20marketing"


async def test_search_files_escapes_odata_quotes():
    ctx = context({"status": 200, "json": {"value": []}})
    await run(ctx, action="search_files", query="it's")
    assert http_requests(ctx)[0]["url"] == f"{DRIVE}/root/search(q='it%27%27s')"


async def test_create_requires_object_fields_before_http():
    """Malformed create payload is rejected before any Graph request."""
    ctx = context()
    output = await run(ctx, action="create_item", fields=[])
    assert output == {"error": "fields must be a non-empty JSON object"}
    assert http_requests(ctx) == []


async def test_create_item_accepts_json_text_from_input_data():
    ctx = context({"status": 201, "json": {"id": "7"}})
    output = await run(ctx, input_data={"fields": '{"Title": "New"}'}, action="create_item")
    request = http_requests(ctx)[0]
    assert (request["method"], request["url"]) == ("POST", f"{SITE}/lists/list-1/items")
    assert request["json"] == {"fields": {"Title": "New"}}
    assert output["result"] == {"id": "7"}


async def test_update_item_patches_fields():
    ctx = context({"status": 200, "json": {"Title": "Changed"}})
    await run(ctx, action="update_item", item_id="7", fields={"Title": "Changed"})
    request = http_requests(ctx)[0]
    assert (request["method"], request["url"]) == ("PATCH", f"{SITE}/lists/list-1/items/7/fields")
    assert request["json"] == {"Title": "Changed"}


@pytest.mark.parametrize(
    ("action", "url"),
    [("delete_item", f"{SITE}/lists/list-1/items/7"), ("delete_file", f"{DRIVE}/items/7")],
)
async def test_delete_actions_delete_one_item_by_id(action, url):
    ctx = context({"status": 204})
    output = await run(ctx, action=action, item_id="7")
    request = http_requests(ctx)[0]
    assert (request["method"], request["url"]) == ("DELETE", url)
    assert output == {"action": action, "result": {"status": 204}}


async def test_delete_requires_item_id_before_http():
    ctx = context()
    output = await run(ctx, action="delete_file", item_id="")
    assert output == {"error": "item_id is required"}
    assert http_requests(ctx) == []


async def test_upload_text_sends_bytes_as_data():
    """Text uploads use data=, the keyword the platform's http capability accepts."""
    ctx = context({"status": 201, "json": {"id": "file-1"}})
    output = await run(ctx, action="upload_text", path="/folder/my file.txt", content="hello")
    request = http_requests(ctx)[0]
    assert request["method"] == "PUT"
    assert request["url"] == f"{DRIVE}/root:/folder/my%20file.txt:/content"
    assert request["data"] == b"hello"
    assert request["headers"]["Content-Type"] == "text/plain; charset=utf-8"
    assert "content" not in request
    assert output["result"] == {"id": "file-1"}


async def test_upload_text_enforces_size_limit():
    ctx = context()
    output = await run(ctx, action="upload_text", path="a.txt", content="é" * 600_000)
    assert output == {"error": "Text content exceeds the 1 MB limit"}
    assert http_requests(ctx) == []


@pytest.mark.parametrize("path", ["../secret.txt", "a/./b.txt", "  /  "])
async def test_paths_must_stay_inside_the_library(path):
    ctx = context()
    output = await run(ctx, action="upload_text", path=path, content="x")
    assert "path" in output["error"]
    assert http_requests(ctx) == []


async def test_create_folder_posts_to_parent_and_fails_on_conflict():
    ctx = context({"status": 201, "json": {"id": "folder-1"}})
    await run(ctx, action="create_folder", path="Reports/2026")
    request = http_requests(ctx)[0]
    assert (request["method"], request["url"]) == ("POST", f"{DRIVE}/root:/Reports:/children")
    assert request["json"] == {"name": "2026", "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}


async def test_list_files_in_folder_or_root():
    ctx = context({"status": 200, "json": {"value": []}}, {"status": 200, "json": {"value": []}})
    await run(ctx, action="list_files", path="Reports")
    await run(ctx, action="list_files", path="")
    assert [request["url"] for request in http_requests(ctx)] == [
        f"{DRIVE}/root:/Reports:/children", f"{DRIVE}/root/children",
    ]


async def test_download_text_returns_utf8_text():
    ctx = context({"status": 200, "body": "héllo".encode()})
    output = await run(ctx, action="download_text", item_id="file-1")
    assert http_requests(ctx)[0]["url"] == f"{DRIVE}/items/file-1/content"
    assert output == {"action": "download_text", "result": "héllo"}


@pytest.mark.parametrize(
    ("body", "error"),
    [(b"\xff\xfe\x00", "not valid UTF-8"), (b"a" * 1_000_001, "1 MB")],
)
async def test_download_text_rejects_binary_and_large_files(body, error):
    ctx = context({"status": 200, "body": body})
    output = await run(ctx, action="download_text", item_id="file-1")
    assert error in output["error"]


async def test_site_id_is_required_before_http():
    ctx = context()
    output = await run(ctx, action="list_lists", site_id="")
    assert output == {"error": "site_id is required"}
    assert http_requests(ctx) == []


async def test_graph_errors_return_status_and_code_only():
    """The Graph error code is shown; its message and the token never are."""
    ctx = context({"status": 404, "json": {"error": {"code": "itemNotFound", "message": "secret detail"}}})
    output = await run(ctx, action="get_file", item_id="missing")
    assert output == {"error": "Microsoft Graph returned HTTP 404 (itemNotFound); check permissions and inputs"}
    assert TOKEN not in str(output)


async def test_capability_failure_returns_generic_error():
    ctx = context()  # no queued response: the fake http capability raises
    output = await run(ctx, action="get_item", item_id="7")
    assert output == {"error": "Microsoft Graph credential or request failed"}


async def test_unsupported_action_is_rejected_before_credentials():
    ctx = context()
    output = await run(ctx, action="drop_site")
    assert output == {"error": "Unsupported SharePoint action"}
    assert ctx.calls == []
