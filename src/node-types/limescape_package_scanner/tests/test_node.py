from pathlib import Path

from limescape_plugin_sdk.testing import FakeContext, run_node

NODE = Path(__file__).resolve().parents[1]
PAT_TYPE = "limescapeAzureDevOpsPatApi"


def context(*responses, secret="synthetic-token", credential_type=PAT_TYPE):
    return FakeContext(
        granted=["credentials", "http"],
        credential_resolver=lambda ref, **kwargs: {
            "reference": ref, "type_name": credential_type,
            "values": {"pat": secret, "accessToken": secret},
        },
        http_responses=list(responses),
    )


async def run(ctx, **params):
    return await run_node(NODE, ctx, params=params, output_key="result")


async def test_missing_credential_stops_before_http():
    ctx = context()
    output = await run(ctx, auth_mode="pat", credential_selection="team", credential_code="", organization="o", project="p", web_repository="w", core_repository="c")
    assert "Select the matching" in output[0]["result"]["error"]
    assert not [c for c in ctx.calls if c.capability == "http"]


async def test_credentials_are_resolved_and_release_scan_is_performed():
    ctx = context(
        {"status": 200, "json": {"value": [{"name": "refs/heads/develop"}]}},
        {"status": 200, "json": {"value": [{"name": "refs/heads/develop"}]}},
        {"status": 200, "json": {"value": []}},
        {"status": 200, "json": {"value": [{"name": "refs/heads/develop"}]}},
        {"status": 200, "json": {"value": []}},
    )
    result = await run(ctx, auth_mode="pat", credential_selection="team", credential_code="devops-team", organization="o", project="p", web_repository="w", core_repository="c")
    assert result[0]["result"]["onderdelen"] == "alles"
    assert any(c.capability == "http" for c in ctx.calls)


async def test_invalid_scope_is_rejected():
    ctx = context()
    result = await run(ctx, auth_mode="pat", credential_selection="team", credential_code="devops-team", organization="o", project="p", web_repository="w", core_repository="c", onderdelen="invalid")
    assert result[0]["result"]["error"] == "onderdelen must be alles, componenten, or kwetsbaarheden"


async def test_pat_never_appears_in_report():
    ctx = context({"status": 403, "json": {"message": "synthetic-token"}}, secret="secret-that-must-not-leak")
    result = await run(ctx, auth_mode="pat", credential_selection="team", credential_code="devops-team", organization="o", project="p", web_repository="w", core_repository="c")
    assert "secret-that-must-not-leak" not in str(result)
