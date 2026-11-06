import base64
import json
from pathlib import Path

from limescape_plugin_sdk.testing import FakeContext, run_node

NODE = Path(__file__).resolve().parents[1]
CREDENTIAL_TYPE = "genericSecret"
DEVOPS = "https://dev.azure.com/o/p/_apis/git/repositories/"
GITHUB = "https://api.github.com/repos/"
DEPS_DEV = "https://api.deps.dev/v3/systems/"
GHSA = "GHSA-5crp-9r3c-p9vr"

WEB_CSPROJ = b'''<Project>
  <PackageReference Include="Newtonsoft.Json" Version="12.0.1" />
  <PackageReference Include="IdentityServer4" Version="4.1.2" />
  <PackageReference Include="Contoso.Internal" Version="1.0.0" />
  <PackageReference Include="Aspose.PDF" Version="$(AsposeVersion)" />
</Project>'''
CORE_PROPS = '''﻿<Project>
  <PackageVersion Include="NLog">
    <Version>4.7.0</Version>
  </PackageVersion>
</Project>'''.encode()


def _json(value, status=200, headers=None):
    return {"status": status, "json": value, **({"headers": headers} if headers else {})}


def _deps_dev(url):
    """deps.dev package versions; 'Contoso.Internal' only exists on a private feed."""
    if url.endswith("/Contoso.Internal"):
        return {"status": 404, "text": "not found"}
    return _json({"versions": [
        {"versionKey": {"version": "13.0.1"}, "publishedAt": "2022-01-01T00:00:00Z", "isDefault": False},
        {"versionKey": {"version": "13.0.3"}, "publishedAt": "2023-03-08T07:42:54Z", "isDefault": True},
        {"versionKey": {"version": "14.0.0-beta1"}, "publishedAt": "2024-01-01T00:00:00Z", "isDefault": False},
    ]})


def _backend(request):
    """A small synthetic Azure DevOps / OSV / deps.dev backend routed by URL."""
    url, params = request["url"], request.get("params") or {}
    if url == DEVOPS + "w":
        return _json({"defaultBranch": "refs/heads/develop"})  # develop is already covered by git-flow
    if url == DEVOPS + "c":
        return _json({})  # no default branch
    if url.endswith("/refs"):
        repo = url.removeprefix(DEVOPS).removesuffix("/refs")
        if params["filter"] != "heads/release/":
            return _json({"value": []})
        if repo == "w" and "continuationToken" not in params:
            # first page: a non-version branch plus a continuation token
            return _json({"value": [{"name": "refs/heads/release/notes", "objectId": "x"}]},
                         headers={"x-ms-continuationtoken": "page-2"})
        if repo == "w":
            return _json({"value": [{"name": "refs/heads/release/9.2.1", "objectId": "cw"},
                                    {"name": "refs/heads/release/9.2.0-RC1", "objectId": "cw-rc"},
                                    {"name": "refs/heads/release/7.9.0", "objectId": "too-old"}]})
        return _json({"value": [{"name": "refs/heads/release/9.2.0", "objectId": "cc"},
                                {"name": "refs/heads/release/2019.1.0", "objectId": "cc-2019"}]})
    if "/commits/" in url:
        return _json({"treeId": "tree-" + url.rsplit("/", 1)[1]})
    if url.endswith("/trees/tree-cw"):
        return _json({"treeEntries": [
            {"relativePath": "src/App/App.csproj", "objectId": "b-web", "gitObjectType": "blob"},
            {"relativePath": "src/App.Tests/App.Tests.csproj", "objectId": "b-test", "gitObjectType": "blob"},
            {"relativePath": "src", "objectId": "t-src", "gitObjectType": "tree"},
        ]})
    if url.endswith(("/trees/tree-cc", "/trees/tree-cc-2019", "/trees/tree-cc-main")):
        return _json({"treeEntries": [
            {"relativePath": "Core/Directory.Packages.props", "objectId": "b-core", "gitObjectType": "blob"},
        ]})
    if url.endswith("/blobs/b-web"):
        return {"status": 200, "body": WEB_CSPROJ}
    if url.endswith("/blobs/b-core"):
        return {"status": 200, "body": CORE_PROPS}
    if url == "https://api.osv.dev/v1/querybatch":
        queries = request["json"]["queries"]
        return _json({"results": [{"vulns": [{"id": GHSA}]} if q["package"]["name"] == "Newtonsoft.Json" else {}
                                  for q in queries]})
    if url == f"https://api.osv.dev/v1/vulns/{GHSA}":
        return _json({"id": GHSA, "summary": "Improper | handling", "aliases": ["CVE-2024-21907", "GHSA-x"],
                      "database_specific": {"severity": "HIGH"},
                      "affected": [{"package": {"name": "Newtonsoft.Json"},
                                    "ranges": [{"events": [{"introduced": "0"}, {"fixed": "13.0.1"}]}]}]})
    if url.startswith(DEPS_DEV):
        return _deps_dev(url)
    return {"status": 404, "text": "not found"}


def context(*responses, credential_value="synthetic-token", handler=None, resolved=None):
    def resolver(reference, **kwargs):
        if resolved is not None:
            resolved.append((kwargs.get("expected_type"), kwargs.get("mode"), kwargs.get("oauth2")))
        return {"reference": reference, "type_name": CREDENTIAL_TYPE, "values": {"secret": credential_value}}

    return FakeContext(
        granted=["credentials", "http"],
        credential_resolver=resolver,
        http_responses=list(responses),
        http_handler=handler,
    )


async def run(ctx, **params):
    return await run_node(NODE, ctx, params=params, output_key="result")


def scan_params(**extra):
    return {"credential_code": "devops-team", "organization": "o", "project": "p", "repositories": "w, c",
            "min_major": 8, "max_major": 999, "exclude_packages": "IdentityServer4", **extra}


def http_calls(ctx):
    return [c.request for c in ctx.calls if c.capability == "http"]


# ---------------------------------------------------------------- validation and safe errors

async def test_missing_credential_stops_before_http():
    ctx = context()
    output = await run(ctx, **scan_params(credential_code=""))
    assert "Select the team credential with the Azure DevOps personal access token" in output[0]["result"]["error"]
    assert not http_calls(ctx)


async def test_missing_repositories_stops_before_http():
    ctx = context()
    output = await run(ctx, **scan_params(repositories=" , "))
    assert output[0]["result"]["error"] == "repositories is required"
    assert not http_calls(ctx)


async def test_azure_devops_requires_project_but_github_does_not():
    ctx = context()
    output = await run(ctx, **scan_params(project=""))
    assert output[0]["result"]["error"] == "project is required"
    assert not http_calls(ctx)


async def test_invalid_scan_scope_provider_and_package_type_return_safe_errors():
    for params, fout in ((scan_params(onderdelen="invalid"), "onderdelen must be"),
                         (scan_params(provider="gitlab"), "provider must be azure_devops or github"),
                         (scan_params(ecosystems="nuget, cobol"), "Unknown package type 'cobol'")):
        ctx = context()
        result = await run(ctx, **params)
        assert fout in result[0]["result"]["error"]
        assert not http_calls(ctx)


async def test_empty_release_scan_returns_report():
    """Two repositories x (three ref prefixes + repository info); no branches means no tree requests."""
    empty = {"status": 200, "json": {"value": []}}
    ctx = context(*([empty] * 8))
    result = await run(ctx, **scan_params(onderdelen="kwetsbaarheden"))
    report = result[0]["result"]
    assert report["onderdelen"] == "kwetsbaarheden"
    assert report["releases"] == []
    assert report["waarschuwingen"] == []
    assert len(http_calls(ctx)) == 8


async def test_pat_never_appears_in_report():
    ctx = context({"status": 403, "json": {"message": "synthetic-token"}}, credential_value="secret-that-must-not-leak")
    result = await run(ctx, **scan_params())
    assert "secret-that-must-not-leak" not in str(result)


async def test_invalid_pat_sign_in_page_reports_access_denied():
    """Azure DevOps answers an invalid PAT with 203 and an HTML sign-in page."""
    ctx = context({"status": 203, "text": "<html>Sign in</html>"})
    result = await run(ctx, **scan_params())
    assert "weigert de toegang" in result[0]["result"]["error"]


# ---------------------------------------------------------------- Azure DevOps scans

async def test_full_scan_reports_packages_vulnerabilities_and_newest_versions():
    resolved: list = []
    ctx = context(handler=_backend, resolved=resolved)
    result = await run(ctx, **scan_params(markdown=True))
    report = result[0]["result"]
    assert resolved == [(CREDENTIAL_TYPE, "team", False)]

    assert [r["release_lijn"] for r in report["releases"]] == ["9.2"]
    release = report["releases"][0]
    assert release["versie"] == "9.2.1"
    assert release["branches"] == {"w": ["release/9.2.1"], "c": ["release/9.2.0"]}
    assert release["packages"] == {"nuget": {
        "Contoso.Internal": {"w": "1.0.0"},
        "Newtonsoft.Json": {"w": "12.0.1"},
        "NLog": {"c": "4.7.0"},
    }}  # IdentityServer4 is excluded, MSBuild-variable versions are skipped

    assert release["kwetsbaarheden"] == [{
        "ecosystem": "nuget", "package": "Newtonsoft.Json", "repo": "w", "versie": "12.0.1", "direct": True,
        "severity": "HIGH", "advisory": GHSA, "cve": "CVE-2024-21907", "gefixt_in": "13.0.1",
        "samenvatting": "Improper | handling",
    }]
    assert release["aantal_kwetsbare_packages"] == 1
    assert release["hoogste_severity"] == "HIGH"

    assert report["nieuwste_versies"] == {"nuget": {
        "Contoso.Internal": {"nieuwste": None, "datum": "", "status": "niet gevonden op nuget.org"},
        "Newtonsoft.Json": {"nieuwste": "13.0.3", "datum": "08-03-2023", "status": "ok"},
        "NLog": {"nieuwste": "13.0.3", "datum": "08-03-2023", "status": "ok"},
    }}
    assert report["waarschuwingen"] == []
    assert report["uitgesloten_packages"] == ["identityserver4"]
    assert report["bron"] == "Azure DevOps o/p: w, c"
    assert report["ecosystemen"] == ["nuget", "npm", "pypi", "go", "maven", "composer", "rubygems", "cargo"]
    assert report["statistiek"]["w"] == {"branches": 1, "projectbestanden": 1, "gelezen": 1, "dependencies": 2,
                                         "direct": 2}
    assert report["statistiek"]["c"] == {"branches": 1, "projectbestanden": 1, "gelezen": 1, "dependencies": 1,
                                         "direct": 1}

    assert "|nuget|NLog|4.7.0|13.0.3|08-03-2023|" in report["markdown"]["packages_per_release"]["9.2"]
    assert GHSA in report["markdown"]["kwetsbaarheden"]
    assert "Improper \\| handling" in report["markdown"]["kwetsbaarheden"]

    calls = http_calls(ctx)
    osv_query = next(c for c in calls if c["url"].endswith("/querybatch"))
    assert {q["package"]["name"] for q in osv_query["json"]["queries"]} == {"Contoso.Internal", "Newtonsoft.Json",
                                                                           "NLog"}
    assert {q["package"]["ecosystem"] for q in osv_query["json"]["queries"]} == {"NuGet"}
    assert not any(c["url"].endswith("/blobs/b-test") for c in calls)  # test projects are excluded by default
    assert any(c.get("params", {}).get("continuationToken") == "page-2" for c in calls)
    basic = "Basic " + base64.b64encode(b":synthetic-token").decode()  # PAT as Basic auth, empty user name
    for call in calls:
        headers = call.get("headers") or {}
        assert ("Authorization" in headers) == call["url"].startswith("https://dev.azure.com/")  # token stays there
        if "Authorization" in headers:
            assert headers["Authorization"] == basic


async def test_latest_packages_list_limits_registry_lookups():
    ctx = context(handler=_backend)
    result = await run(ctx, **scan_params(onderdelen="componenten", latest_packages="NLog"))
    report = result[0]["result"]
    assert list(report["nieuwste_versies"]["nuget"]) == ["NLog"]
    lookups = [c["url"] for c in http_calls(ctx) if c["url"].startswith(DEPS_DEV)]
    assert lookups == [DEPS_DEV + "nuget/packages/NLog"]
    release = report["releases"][0]
    assert "kwetsbaarheden" not in release and "hoogste_severity" not in release
    assert not any("osv.dev" in c["url"] for c in http_calls(ctx))


async def test_major_range_and_release_line_selection():
    ctx = context(handler=_backend)
    result = await run(ctx, **scan_params(onderdelen="kwetsbaarheden", max_major=""))
    lines = [r["release_lijn"] for r in result[0]["result"]["releases"]]
    assert lines == ["2019.1", "9.2"]  # without max_major year-numbered branches count as newest
    assert "packages" not in result[0]["result"]["releases"][0]

    ctx = context(handler=_backend)
    result = await run(ctx, **scan_params(onderdelen="kwetsbaarheden", release_lines="9.1"))
    assert result[0]["result"]["releases"] == []

    ctx = context(handler=_backend)
    result = await run(ctx, **scan_params(onderdelen="kwetsbaarheden", release_lines="9.2.0"))
    assert [r["release_lijn"] for r in result[0]["result"]["releases"]] == ["9.2"]

    ctx = context()
    result = await run(ctx, **scan_params(min_major=10, max_major=9))
    assert result[0]["result"]["error"] == "max_major must be at least min_major"


async def test_azure_default_branch_is_its_own_line():
    def handler(request):
        url, params = request["url"], request.get("params") or {}
        if url == DEVOPS + "c":
            return _json({"defaultBranch": "refs/heads/main"})
        if url == DEVOPS + "c/refs" and params.get("filter") == "heads/main":
            return _json({"value": [{"name": "refs/heads/main-old", "objectId": "wrong"},
                                    {"name": "refs/heads/main", "objectId": "cc-main"}]})
        return _backend(request)

    ctx = context(handler=handler)
    result = await run(ctx, **scan_params(onderdelen="componenten", latest_packages="NLog"))
    releases = result[0]["result"]["releases"]
    assert [r["release_lijn"] for r in releases] == ["main", "9.2"]  # the default branch comes first
    assert releases[0]["branches"] == {"c": ["main"]}
    assert releases[0]["packages"] == {"nuget": {"NLog": {"c": "4.7.0"}}}
    assert not any(c["url"].endswith("/commits/wrong") for c in http_calls(ctx))

    ctx = context(handler=handler)
    result = await run(ctx, **scan_params(onderdelen="componenten", latest_packages="NLog",
                                          include_default_branch=False))
    assert [r["release_lijn"] for r in result[0]["result"]["releases"]] == ["9.2"]
    assert not any(c["url"] in (DEVOPS + "w", DEVOPS + "c") for c in http_calls(ctx))


async def test_custom_path_exclusion_skips_project_files():
    ctx = context(handler=_backend)
    result = await run(ctx, **scan_params(onderdelen="componenten", latest_packages="NLog", exclude_paths="src/app/"))
    release = result[0]["result"]["releases"][0]
    assert release["packages"] == {"nuget": {"NLog": {"c": "4.7.0"}}}


async def test_package_type_filter_skips_other_files():
    ctx = context(handler=_backend)
    result = await run(ctx, **scan_params(onderdelen="kwetsbaarheden", ecosystems=["npm", "python"]))
    report = result[0]["result"]
    assert report["ecosystemen"] == ["npm", "pypi"]
    assert report["releases"][0]["kwetsbaarheden"] == []
    assert not any("/blobs/" in c["url"] for c in http_calls(ctx))


async def test_unreadable_project_file_becomes_warning():
    def handler(request):
        if request["url"].endswith("/blobs/b-core"):
            return {"status": 400, "text": "boom"}
        return _backend(request)

    ctx = context(handler=handler)
    result = await run(ctx, **scan_params(onderdelen="kwetsbaarheden"))
    report = result[0]["result"]
    assert "c: Core/Directory.Packages.props niet gelezen (NodeInputError)" in report["waarschuwingen"]
    assert report["releases"][0]["aantal_kwetsbare_packages"] == 1


# ---------------------------------------------------------------- GitHub scans

PACKAGE_JSON = {"name": "web", "dependencies": {"lodash": "^4.17.0"}}
NPM_LOCK_MAIN = {"lockfileVersion": 3, "packages": {
    "": {"name": "web", "dependencies": {"lodash": "^4.17.0"}},
    "node_modules/lodash": {"version": "4.17.15"},
    "node_modules/minimist": {"version": "1.2.5"},
}}
NPM_LOCK_V1 = {"lockfileVersion": 1, "dependencies": {"lodash": {"version": "4.17.10"}}}
REQUIREMENTS = "requests==2.19.0\n    # via -r requirements.in\nurllib3==1.24.1\n    # via requests\n"
GO_MOD = "module example.com/lib\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.6.0\n" \
         "\tgolang.org/x/sys v0.1.0 // indirect\n)\n"
BLOBS = {
    "b-lock-main": json.dumps(NPM_LOCK_MAIN), "b-lock-211": json.dumps(NPM_LOCK_V1),
    "b-pkg": json.dumps(PACKAGE_JSON), "b-req": REQUIREMENTS, "b-gomod": GO_MOD,
}
ADVISORIES = {
    "GHSA-lodash-0001": {"summary": "Prototype pollution in lodash", "aliases": ["CVE-2020-8203"],
                         "database_specific": {"severity": "HIGH"},
                         "affected": [{"package": {"name": "lodash"}, "ranges": [{"events": [{"fixed": "4.17.19"}]}]}]},
    "GHSA-x84v-xcm2-53pg": {"summary": "Insufficiently protected credentials in Requests",
                            "aliases": ["CVE-2018-18074", "PYSEC-2018-28"],
                            "database_specific": {"severity": "MODERATE"},
                            "affected": [{"package": {"name": "requests"},
                                          "ranges": [{"events": [{"fixed": "2.20.0"}]}]}]},
    "PYSEC-2018-28": {"details": "The Requests package before 2.20.0 ...", "aliases": ["CVE-2018-18074",
                                                                                        "GHSA-x84v-xcm2-53pg"]},
    "GHSA-urllib-0001": {"summary": "CRLF injection in urllib3", "database_specific": {"severity": "LOW"},
                         "affected": [{"package": {"name": "urllib3"}, "ranges": [{"events": [{"fixed": "1.24.2"}]}]}]},
    "GHSA-h395-qcrw-5vmq": {"summary": "Inconsistent interpretation of HTTP requests in gin",
                            "aliases": ["CVE-2020-28483", "GO-2021-0052"], "database_specific": {"severity": "HIGH"},
                            "affected": [{"package": {"name": "github.com/gin-gonic/gin"},
                                          "ranges": [{"events": [{"fixed": "1.7.7"}]}]}]},
    "GO-2021-0052": {"summary": "Inconsistent interpretation of HTTP requests",
                     "aliases": ["CVE-2020-28483", "GHSA-h395-qcrw-5vmq"]},
}
OSV_HITS = {
    ("npm", "lodash", "4.17.15"): ["GHSA-lodash-0001"], ("npm", "lodash", "4.17.10"): ["GHSA-lodash-0001"],
    ("PyPI", "requests", "2.19.0"): ["GHSA-x84v-xcm2-53pg", "PYSEC-2018-28"],
    ("PyPI", "urllib3", "1.24.1"): ["GHSA-urllib-0001"],
    ("Go", "github.com/gin-gonic/gin", "v1.6.0"): ["GHSA-h395-qcrw-5vmq", "GO-2021-0052"],
}
WEB = GITHUB + "acme/web"
LIB = GITHUB + "other-org/lib"
RELEASE_PAGE_2 = "https://api.github.com/repositories/1/git/matching-refs/heads/release/?page=2"


def _blob(sha):
    return _json({"sha": sha, "encoding": "base64", "content": base64.b64encode(BLOBS[sha].encode()).decode()})


def _github(request):
    """A synthetic GitHub / OSV / deps.dev backend: acme/web (npm + Python) and other-org/lib (Go)."""
    url = request["url"]
    routes = {
        WEB: _json({"default_branch": "main"}),
        WEB + "/git/matching-refs/heads/develop": _json([]),
        WEB + "/git/matching-refs/heads/release/": _json(
            [{"ref": "refs/heads/release/2.1.0", "object": {"sha": "r210", "type": "commit"}}],
            headers={"link": f'<{RELEASE_PAGE_2}>; rel="next"'}),
        RELEASE_PAGE_2: _json(
            [{"ref": "refs/heads/release/2.1.1", "object": {"sha": "r211", "type": "commit"}}],
            headers={"link": '<https://evil.example/steal>; rel="next"'}),  # another host is never followed
        WEB + "/git/matching-refs/heads/hotfix/": _json([]),
        WEB + "/git/ref/heads/main": _json({"object": {"sha": "m1", "type": "commit"}}),
        WEB + "/git/trees/m1": _json({"truncated": False, "tree": [
            {"path": "package-lock.json", "type": "blob", "sha": "b-lock-main", "size": 100},
            {"path": "package.json", "type": "blob", "sha": "b-pkg", "size": 50},
            {"path": "requirements.txt", "type": "blob", "sha": "b-req", "size": 50},
            {"path": "node_modules/foo/package.json", "type": "blob", "sha": "b-node-modules", "size": 10},
            {"path": "big/package-lock.json", "type": "blob", "sha": "b-big", "size": 30_000_000},
            {"path": "README.md", "type": "blob", "sha": "b-readme", "size": 10},
            {"path": "src", "type": "tree", "sha": "t-src"},
        ]}),
        WEB + "/git/trees/r211": _json({"truncated": True, "tree": [
            {"path": "package-lock.json", "type": "blob", "sha": "b-lock-211", "size": 100},
            {"path": "package.json", "type": "blob", "sha": "b-pkg", "size": 50},
        ]}),
        LIB: _json({"default_branch": "master"}),
        LIB + "/git/matching-refs/heads/develop": _json([]),
        LIB + "/git/matching-refs/heads/release/": _json([]),
        LIB + "/git/ref/heads/master": _json({"object": {"sha": "l1", "type": "commit"}}),
        LIB + "/git/trees/l1": _json({"tree": [{"path": "go.mod", "type": "blob", "sha": "b-gomod", "size": 80}]}),
    }
    if url in routes:
        return routes[url]
    if "/git/blobs/" in url:
        return _blob(url.rsplit("/", 1)[1])
    if url == "https://api.osv.dev/v1/querybatch":
        return _json({"results": [
            {"vulns": [{"id": i} for i in OSV_HITS.get((q["package"]["ecosystem"], q["package"]["name"],
                                                        q["version"]), [])]}
            for q in request["json"]["queries"]]})
    if url.startswith("https://api.osv.dev/v1/vulns/"):
        advisory_id = url.rsplit("/", 1)[1]
        return _json({"id": advisory_id, **ADVISORIES[advisory_id]})
    if url.startswith(DEPS_DEV):
        return _json({"versions": [{"versionKey": {"version": "9.9.9"}, "publishedAt": "2026-01-02T00:00:00Z",
                                    "isDefault": True}]})
    return {"status": 404, "text": "not found"}


def github_params(**extra):
    return {"provider": "github", "credential_code": "gh-team", "organization": "acme",
            "repositories": "web, other-org/lib", **extra}


async def test_github_scan_reports_npm_python_and_go():
    resolved: list = []
    ctx = context(handler=_github, resolved=resolved, credential_value="github-token")
    result = await run(ctx, **github_params(markdown=True))
    report = result[0]["result"]
    assert resolved == [(CREDENTIAL_TYPE, "team", False)]
    assert report["bron"] == "GitHub acme: web, other-org/lib"

    assert [r["release_lijn"] for r in report["releases"]] == ["main", "master", "2.1"]
    main, master, release = report["releases"]
    assert main["branches"] == {"web": ["main"]}
    assert master["branches"] == {"other-org/lib": ["master"]}
    assert release["versie"] == "2.1.1" and release["branches"] == {"web": ["release/2.1.1"]}

    # only direct dependencies are listed; transitive ones (minimist, urllib3, x/sys) are scanned for advisories
    assert main["packages"] == {"npm": {"lodash": {"web": "4.17.15"}}, "pypi": {"requests": {"web": "2.19.0"}}}
    assert master["packages"] == {"go": {"github.com/gin-gonic/gin": {"other-org/lib": "v1.6.0"}}}
    # a lockfile v1 has no direct markers: package.json of the same branch marks lodash as direct
    assert release["packages"] == {"npm": {"lodash": {"web": "4.17.10"}}}

    assert [(r["package"], r["severity"], r["direct"], r["advisory"], r["cve"]) for r in main["kwetsbaarheden"]] == [
        ("lodash", "HIGH", True, "GHSA-lodash-0001", "CVE-2020-8203"),
        ("requests", "MODERATE", True, "GHSA-x84v-xcm2-53pg", "CVE-2018-18074"),  # PYSEC duplicate merged
        ("urllib3", "LOW", False, "GHSA-urllib-0001", ""),
    ]
    assert main["kwetsbaarheden"][1]["gefixt_in"] == "2.20.0"
    assert main["hoogste_severity"] == "HIGH" and main["aantal_kwetsbare_packages"] == 3
    assert [(r["advisory"], r["cve"], r["gefixt_in"]) for r in master["kwetsbaarheden"]] == [
        ("GHSA-h395-qcrw-5vmq", "CVE-2020-28483", "1.7.7")]  # GO-2021-0052 duplicate merged

    assert report["nieuwste_versies"] == {
        "npm": {"lodash": {"nieuwste": "9.9.9", "datum": "02-01-2026", "status": "ok"}},
        "pypi": {"requests": {"nieuwste": "9.9.9", "datum": "02-01-2026", "status": "ok"}},
        "go": {"github.com/gin-gonic/gin": {"nieuwste": "9.9.9", "datum": "02-01-2026", "status": "ok"}},
    }
    assert sorted(report["waarschuwingen"]) == [
        "web: bestandsboom van release/2.1.1 is afgekapt; niet alle bestanden zijn gescand",
        "web: big/package-lock.json overgeslagen (groter dan 20 MB)",
    ]
    assert report["statistiek"]["web"]["projectbestanden"] == 4  # two lockfiles, package.json, requirements.txt
    assert "|go|github.com/gin-gonic/gin|v1.6.0|9.9.9|02-01-2026|" in report["markdown"]["packages_per_release"][
        "master"]
    assert "|pypi|urllib3|nee|web 1.24.1|LOW|" in report["markdown"]["kwetsbaarheden"]

    calls = http_calls(ctx)
    urls = [c["url"] for c in calls]
    assert RELEASE_PAGE_2 in urls and not any("evil.example" in u for u in urls)
    assert not any(u.endswith(("/b-node-modules", "/b-big", "/b-readme", "/trees/r210")) for u in urls)
    assert DEPS_DEV + "go/packages/github.com%2Fgin-gonic%2Fgin" in urls
    for call in calls:
        headers = call.get("headers") or {}
        assert ("Authorization" in headers) == call["url"].startswith("https://api.github.com/")
        if "Authorization" in headers:
            assert headers["Authorization"] == "Bearer github-token"
    assert "github-token" not in str(result)


async def test_github_package_type_filter_and_latest_package_prefix():
    ctx = context(handler=_github)
    result = await run(ctx, **github_params(ecosystems="python", onderdelen="componenten",
                                            latest_packages="pypi:urllib3, requests"))
    report = result[0]["result"]
    assert report["ecosystemen"] == ["pypi"]
    # every scanned line is reported, also when it has no files of the selected package type
    assert {r["release_lijn"]: r["packages"] for r in report["releases"]} == {
        "main": {"pypi": {"requests": {"web": "2.19.0"}}}, "master": {}, "2.1": {}}
    assert set(report["nieuwste_versies"]["pypi"]) == {"urllib3", "requests"}
    urls = [c["url"] for c in http_calls(ctx)]
    assert not any(u.endswith(("/b-lock-main", "/b-gomod", "/b-pkg")) for u in urls)

    ctx = context(handler=_github)
    result = await run(ctx, **github_params(onderdelen="componenten", latest_packages="does-not-exist"))
    report = result[0]["result"]
    assert report["nieuwste_versies"] is None
    assert "does-not-exist niet gevonden in de scan; geef de soort op, bijvoorbeeld npm:does-not-exist" in report[
        "waarschuwingen"]


async def test_github_errors_are_safe_and_specific():
    ctx = context({"status": 401, "json": {"message": "Bad credentials"}}, credential_value="leaky")
    result = await run(ctx, **github_params(repositories="web"))
    assert result[0]["result"]["error"] == "GitHub weigert het token: het is ongeldig of verlopen."
    assert "leaky" not in str(result)

    ctx = context({"status": 403, "json": {"message": "API rate limit exceeded"},
                   "headers": {"x-ratelimit-remaining": "0"}})
    result = await run(ctx, **github_params(repositories="web"))
    assert "GitHub-limiet" in result[0]["result"]["error"]
    assert len(http_calls(ctx)) == 1  # an exhausted rate limit is not retried

    ctx = context({"status": 403, "json": {"message": "Resource not accessible"}})
    result = await run(ctx, **github_params(repositories="web"))
    assert "Contents (Read)" in result[0]["result"]["error"]

    missing = {"status": 404, "json": {"message": "Not Found"}}
    ctx = context(*([missing] * 4))
    result = await run(ctx, **github_params(repositories="web"))
    assert result[0]["result"]["error"] == "Niet gevonden op GitHub (of geen toegang): /repos/acme/web"
