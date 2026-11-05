"""Read-only scanner for package versions in Azure DevOps and OSV advisories."""

import base64
import re
from datetime import datetime
from urllib.parse import quote

from limescape_plugin_sdk import NodeContext, NodeInput, NodeInputError

PAT_TYPE = "limescapeAzureDevOpsPatApi"
OAUTH_TYPE = "limescapeAzureDevOpsOAuth2Api"
MAX_FILES = 2500
MAX_PAGES = 20


def _param(inp: NodeInput, name: str, default=None):
    value = inp.input_data.get(name)
    return value if value not in (None, "") else inp.param(name, default)


def _required(inp: NodeInput, name: str) -> str:
    value = _param(inp, name)
    if not isinstance(value, str) or not value.strip():
        raise NodeInputError(f"{name} is required")
    return value.strip()


def _safe_segment(value: str) -> str:
    return quote(value, safe="")


async def _credential(ctx: NodeContext, inp: NodeInput):
    auth = _param(inp, "auth_mode", "pat")
    if auth not in {"pat", "oauth2"}:
        raise NodeInputError("auth_mode must be pat or oauth2")
    selection = _param(inp, "credential_selection", "team")
    if selection not in {"team", "personal", "personal_type"}:
        raise NodeInputError("credential_selection must be team, personal, or personal_type")
    expected = PAT_TYPE if auth == "pat" else OAUTH_TYPE
    reference = _param(inp, "credential_type") if selection == "personal_type" else _param(inp, "credential_code")
    if not isinstance(reference, str) or not reference.strip():
        raise NodeInputError("Select the matching Azure DevOps credential")
    mode = selection
    credential = await ctx.credentials.resolve(reference.strip(), mode=mode, expected_type=expected)
    field = "pat" if auth == "pat" else "accessToken"
    token = credential.values.get(field)
    if not isinstance(token, str) or not token.strip():
        raise NodeInputError(f"The selected credential has no {field} value")
    if auth == "pat":
        value = base64.b64encode((":" + token.strip()).encode()).decode()
        return {"Authorization": "Basic " + value}
    return {"Authorization": "Bearer " + token.strip()}


async def _request(ctx: NodeContext, method: str, url: str, headers: dict, *, params=None):
    response = await ctx.http.request(method, url, headers=headers, params=params, timeout=45)
    if not 200 <= response.status < 300:
        raise NodeInputError(f"External service returned HTTP {response.status}")
    try:
        return response.json()
    except (ValueError, TypeError) as exc:
        raise NodeInputError("External service returned invalid JSON") from exc


def _product_version(branch: str, min_major: int):
    if branch == "develop":
        return "develop"
    match = re.fullmatch(r"(?:release|hotfix)/(.+)", branch)
    if not match or not re.fullmatch(r"\d+(?:\.\d+){1,4}(?:-RC\d+(?:\.\d+)?)?", match.group(1), re.I):
        return None
    version = match.group(1)
    major = int(version.split(".", 1)[0])
    return version if min_major <= major < 1000 else None


def _release_line(version: str):
    parts = version.split("-", 1)[0].split(".")
    return ".".join(parts[:2]) if len(parts) > 1 else parts[0]


def _packages(content: str):
    found = []
    inline = re.compile(r'<Package(?:Reference|Version)\s+(?:Include|Update)="([^"]+)"[^>]*?\bVersion="([^"]+)"', re.I)
    config = re.compile(r'<package\s+id="([^"]+)"\s+version="([^"]+)"', re.I)
    for match in [*inline.finditer(content), *config.finditer(content)]:
        package, version = match.groups()
        if not re.search(r"[$*]", version):
            found.append((package, version.strip()))
    return found


async def _refs(ctx, base, headers):
    result = []
    for prefix in ("heads/develop", "heads/release/", "heads/hotfix/"):
        data = await _request(ctx, "GET", base + "/refs", headers, params={"filter": prefix, "$top": 1000, "api-version": "7.1"})
        for item in data.get("value", []):
            name = item.get("name", "").removeprefix("refs/heads/")
            if name:
                result.append(name)
    return sorted(set(result))


async def _items(ctx, repo_url, branch, headers):
    params = {"scopePath": "/", "recursionLevel": "Full", "includeContentMetadata": "true",
              "versionDescriptor.version": branch, "versionDescriptor.versionType": "branch", "$top": MAX_FILES,
              "api-version": "7.1"}
    data = await _request(ctx, "GET", repo_url + "/items", headers, params=params)
    return data.get("value", []) if isinstance(data, dict) else []


async def _file_text(ctx, repo_url, path, branch, headers):
    params = {"path": path, "includeContent": "true", "versionDescriptor.version": branch,
              "versionDescriptor.versionType": "branch", "api-version": "7.1"}
    response = await ctx.http.request("GET", repo_url + "/items", headers=headers, params=params, timeout=45)
    if not 200 <= response.status < 300:
        return ""
    # Azure DevOps can return plain file content or a JSON item depending on request headers.
    try:
        body = response.json()
        return str(body.get("content", "")) if isinstance(body, dict) else ""
    except (ValueError, TypeError):
        try:
            return response.body.decode("utf-8-sig", errors="replace")
        except (AttributeError, UnicodeDecodeError):
            return ""


async def _scan_repo(ctx, org, project, name, min_major, selected, headers):
    repo = f"https://dev.azure.com/{_safe_segment(org)}/{_safe_segment(project)}/_apis/git/repositories/{_safe_segment(name)}"
    versions = {}
    for branch in await _refs(ctx, repo, headers):
        version = _product_version(branch, min_major)
        if version is None:
            continue
        line = _release_line(version)
        if selected and line not in selected and version not in selected:
            continue
        current = versions.get(line)
        if current is None or version == "develop" or (current != "develop" and tuple(map(int, re.findall(r"\d+", version))) > tuple(map(int, re.findall(r"\d+", current)))):
            versions[line] = version
    output = {}
    for line, version in versions.items():
        branch = "develop" if version == "develop" else None
        if branch is None:
            candidates = [b for b in await _refs(ctx, repo, headers) if _product_version(b, min_major) == version]
            branch = candidates[0] if candidates else "release/" + version
        tree = await _items(ctx, repo, branch, headers)
        packages = []
        for item in tree:
            path = item.get("path", "")
            lower = path.lower()
            if not lower.endswith((".csproj", "packages.config", "directory.packages.props")):
                continue
            if any(term in lower for term in ("sandbox", "loadtest", ".test/", ".tests/", "/testing/", "octopus.tools.")):
                continue
            text = await _file_text(ctx, repo, path, branch, headers)
            packages.extend({"package": p, "version": v, "path": path} for p, v in _packages(text))
        output[line] = {"version": version, "branches": [branch], "packages": packages}
    return output


async def _osv(ctx, headers, packages):
    queries = [{"package": {"ecosystem": "NuGet", "name": p["package"]}, "version": p["version"]} for p in packages]
    if not queries:
        return []
    result = await _request(ctx, "POST", "https://api.osv.dev/v1/querybatch", {"Content-Type": "application/json", **headers}) if False else None
    # ctx.http accepts JSON request bodies via json=; keep OSV credentials out of this public request.
    response = await ctx.http.request("POST", "https://api.osv.dev/v1/querybatch", headers={"Content-Type": "application/json"}, json={"queries": queries}, timeout=60)
    if not 200 <= response.status < 300:
        raise NodeInputError(f"OSV.dev returned HTTP {response.status}")
    try:
        results = response.json().get("results", [])
    except (ValueError, TypeError) as exc:
        raise NodeInputError("OSV.dev returned invalid JSON") from exc
    advisories = []
    for package, match in zip(packages, results):
        for vuln in (match or {}).get("vulns") or []:
            advisories.append({"package": package["package"], "version": package["version"], "advisory": vuln.get("id")})
    return advisories


async def execute(ctx: NodeContext, inp: NodeInput):
    try:
        headers = await _credential(ctx, inp)
        org = _required(inp, "organization")
        project = _required(inp, "project")
        repos = [_required(inp, "web_repository"), _required(inp, "core_repository")]
        try:
            min_major = int(_param(inp, "min_major", 8))
        except (TypeError, ValueError) as exc:
            raise NodeInputError("min_major must be a whole number") from exc
        if min_major < 1 or min_major > 999:
            raise NodeInputError("min_major must be between 1 and 999")
        parts = str(_param(inp, "release_lines", "") or "").split(",")
        selected = {x.strip() for x in parts if x.strip()}
        scope = str(_param(inp, "onderdelen", "alles") or "alles").lower()
        if scope not in {"alles", "componenten", "kwetsbaarheden"}:
            raise NodeInputError("onderdelen must be alles, componenten, or kwetsbaarheden")
        today = datetime.now().strftime("%-d-%-m-%Y")
        repositories = {}
        for name in repos:
            repositories[name] = await _scan_repo(ctx, org, project, name, min_major, selected, headers)
        lines = sorted({line for repo in repositories.values() for line in repo}, reverse=True)
        releases = []
        for line in lines:
            packages = []
            branches = {}
            versions = []
            for repo, rows in repositories.items():
                if line in rows:
                    branches[repo] = rows[line]["branches"]
                    versions.append(rows[line]["version"])
                    packages.extend({**p, "repository": repo} for p in rows[line]["packages"])
            advisories = await _osv(ctx, headers, packages) if scope in {"alles", "kwetsbaarheden"} else []
            row = {"release_lijn": line, "versie": sorted(versions)[-1] if versions else "", "branches": branches,
                   "packages": packages, "aantal_kwetsbare_packages": len({(a["package"], a["version"]) for a in advisories}),
                   "hoogste_severity": "onbekend" if advisories else "-", "kwetsbaarheden": advisories}
            if scope == "componenten":
                row.pop("aantal_kwetsbare_packages")
                row.pop("hoogste_severity")
                row.pop("kwetsbaarheden")
            if scope == "kwetsbaarheden":
                row.pop("packages")
            releases.append(row)
        output = {"gecontroleerd_op": today, "onderdelen": scope,
                  "bron": f"Azure DevOps {org}/{project}: {', '.join(repos)}", "releases": releases,
                  "waarschuwingen": [], "statistiek": {"release_lijnen": len(lines)}}
        if bool(_param(inp, "markdown", False)):
            output["markdown"] = {"kwetsbaarheden": "\n".join(f"{a['package']} {a['version']}: {a['advisory']}" for r in releases for a in r.get("kwetsbaarheden", []))}
        yield {inp.output_key: output}
    except NodeInputError as exc:
        yield {inp.output_key: {"error": str(exc)}}
    except Exception:
        yield {inp.output_key: {"error": "Package scan failed; check credentials, permissions, and service availability"}}
