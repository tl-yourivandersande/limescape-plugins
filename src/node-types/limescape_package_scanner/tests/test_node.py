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


def scan_params(**extra):
    return {"auth_mode": "pat", "credential_selection": "team", "credential_code": "devops-team",
            "organization": "o", "project": "p", "web_repository": "w", "core_repository": "c", **extra}


async def test_missing_credential_stops_before_http():
    ctx = context()
    output = await run(ctx, **scan_params(credential_code=""))
    assert "Select the matching" in output[0]["result"]["error"]
    assert not [c for c in ctx.calls if c.capability == "http"]


async def test_empty_release_scan_returns_report():
    empty = {"status": 200, "json": {"value": []}}
    ctx = context(*([empty] * 8))
    result = await run(ctx, **scan_params())
    report = result[0]["result"]
    assert report["onderdelen"] == "alles"
    assert report["releases"] == []
    assert len([c for c in ctx.calls if c.capability == "http"]) == 8


async def test_invalid_scan_scope_returns_safe_error():
    ctx = context()
    result = await run(ctx, **scan_params(onderdelen="invalid"))
    assert "error" in result[0]["result"]
    assert not [c for c in ctx.calls if c.capability == "http"]


async def test_pat_never_appears_in_report():
    ctx = context({"status": 403, "json": {"message": "synthetic-token"}}, secret="secret-that-must-not-leak")
    result = await run(ctx, **scan_params())
    assert "secret-that-must-not-leak" not in str(result)
