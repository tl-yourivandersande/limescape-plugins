from pathlib import Path

from limescape_plugin_sdk.testing import FakeContext, run_node

NODE_DIR = Path(__file__).resolve().parents[1]
TYPE = "REPLACE_WITH_STUDIO_MICROSOFT_GRAPH_CREDENTIAL_TYPE"
TOKEN = "synthetic-graph-token"


def context(response=None):
    return FakeContext(
        granted=["credentials", "http"],
        credential_resolver=lambda reference, **kwargs: {
            "reference": reference, "type_name": TYPE,
            "values": {"REPLACE_WITH_STUDIO_ACCESS_TOKEN_FIELD": TOKEN},
        },
        http_responses=[response or {"status": 200, "json": {"value": [{"id": "item-1"}]}}],
    )


async def test_list_items_uses_fixed_graph_host_and_resolved_credential():
    """List operation builds a fixed Graph endpoint and sends the resolved token."""
    ctx = context()
    result = await run_node(
        NODE_DIR, ctx,
        params={"credential_mode": "team", "credential_code": "graph-team", "site_id": "site-1", "list_id": "list-1"},
        output_key="records",
    )
    assert ctx.calls[0].request["expected_type"] == TYPE
    assert ctx.calls[1].request["url"] == "https://graph.microsoft.com/v1.0/sites/site-1/lists/list-1/items?$expand=fields"
    assert ctx.calls[1].request["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert result == [{"records": {"action": "list_items", "result": {"value": [{"id": "item-1"}]}}}]


async def test_create_requires_object_fields_before_http():
    """Malformed create payload is rejected before any Graph request."""
    ctx = context()
    result = await run_node(NODE_DIR, ctx, params={"credential_code": "graph-team", "site_id": "s", "list_id": "l", "action": "create_item", "fields": []})
    assert "error" in result[0]
    assert not any(call.capability == "http" for call in ctx.calls)
