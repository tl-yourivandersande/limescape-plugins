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
        http_responses=[response or {"status": 200, "json": {"id": "file-1"}}],
    )


async def test_upload_text_uses_graph_drive_content_endpoint():
    """Text uploads use a fixed Graph drive path and the token from Studio."""
    ctx = context()
    result = await run_node(
        NODE_DIR, ctx,
        params={"credential_code": "graph-team", "site_id": "site", "drive_id": "drive", "action": "upload_text", "path": "folder/a.txt", "content": "hello"},
        output_key="file",
    )
    req = ctx.calls[1].request
    assert req["method"] == "PUT"
    assert req["url"] == "https://graph.microsoft.com/v1.0/sites/site/drives/drive/root:/folder/a.txt:/content"
    assert req["content"] == b"hello"
    assert result[0]["file"]["result"] == {"id": "file-1"}
