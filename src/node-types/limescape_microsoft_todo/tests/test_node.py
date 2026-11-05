from pathlib import Path

from limescape_plugin_sdk.testing import FakeContext, run_node

NODE_DIR = Path(__file__).resolve().parents[1]
TYPE = "REPLACE_WITH_STUDIO_MICROSOFT_GRAPH_CREDENTIAL_TYPE"
TOKEN = "synthetic-graph-token"


def context():
    return FakeContext(
        granted=["credentials", "http"],
        credential_resolver=lambda reference, **kwargs: {
            "reference": reference, "type_name": TYPE,
            "values": {"REPLACE_WITH_STUDIO_ACCESS_TOKEN_FIELD": TOKEN},
        },
        http_responses=[{"status": 200, "json": {"id": "task-1", "title": "Updated"}}],
    )


async def test_update_task_uses_delegated_me_endpoint_and_patch():
    """Task updates are scoped to the delegated user and send only allowed fields."""
    ctx = context()
    await run_node(
        NODE_DIR, ctx,
        params={"credential_code": "graph-team", "task_list_id": "list", "task_id": "task", "action": "update_task", "task": {"title": "Updated"}},
        output_key="task_result",
    )
    req = ctx.calls[1].request
    assert req["method"] == "PATCH"
    assert req["url"] == "https://graph.microsoft.com/v1.0/me/todo/lists/list/tasks/task"
    assert req["json"] == {"title": "Updated"}
    assert req["headers"]["Authorization"] == f"Bearer {TOKEN}"


async def test_update_task_rejects_unapproved_fields():
    """Extra task properties fail before network access."""
    ctx = context()
    result = await run_node(
        NODE_DIR, ctx,
        params={"credential_code": "graph-team", "task_list_id": "list", "task_id": "task", "action": "update_task", "task": {"title": "x", "id": "other"}},
    )
    assert "error" in result[0]["output"]
    assert not any(call.capability == "http" for call in ctx.calls)
