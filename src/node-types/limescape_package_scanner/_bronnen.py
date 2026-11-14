"""Read-only Git sources: Azure DevOps and GitHub (branches, recursive file tree and file contents).

Both sources expose the same small interface:

- ``git_flow_branches(repo)``: ``[(branch, commit)]`` for develop, release/* and hotfix/*
- ``standaard_branch(repo)``: ``(branch, commit)`` of the repository's default branch, or None
- ``bestanden(repo, commit)``: ``([(path, object id, size or None)], truncated)``
- ``lees(repo, object id)``: the file contents as bytes

The credential header is only ever sent to the source's own API host.
"""

import asyncio
import base64
import re

from limescape_plugin_sdk import CapabilityError, NodeContext, NodeInputError

from ._gedeeld import json_van, seg

AZURE_API_VERSION = "7.1"
GITHUB_API = "https://api.github.com"
MAX_REF_PAGES = 20
RETRY_STATUS = {429, 500, 502, 503, 504}
AZURE_DENIED = {203, 302, 401, 403}
GIT_FLOW = ("develop", "release/", "hotfix/")
USER_AGENT = "limescape-package-scanner"
LINK_NEXT = re.compile(r'<([^>]+)>\s*;\s*rel="next"')

# A personal access token is a team credential of the platform's generic "Secret" type. GitHub can also use the
# platform's GitHub type (a GitHub App user token): the platform refreshes that token and only hands over the access
# token, never the refresh token or client secret. Azure DevOps OAuth is not supported: the platform's Azure DevOps
# OAuth type issues tokens for the Azure DevOps MCP server, not for the REST API.
PAT_TYPE = "genericSecret"
PAT_FIELD = "secret"
GITHUB_OAUTH_TYPE = "githubOAuth2Api"
OAUTH_FIELD = "accessToken"
# The credential dropdown stores a credential code, or "@user:<type>" for the credential of that type of whoever
# starts the flow (the platform's [Aanroeper] choice).
USER_PREFIX = "@user:"

# Platform refusals (CapabilityError.code) as an actionable message; the platform's own text is not passed on.
WEIGERING = {
    "not_found": "De gekozen credential bestaat niet of is niet actief in dit team.",
    "wrong_type": "De gekozen credential past niet bij deze Git-bron. Gebruik een Secret met een personal access "
                  "token, of voor GitHub een GitHub-credential.",
    "ambiguous": "Meer dan één credential past bij de keuze.",
    "oauth_failed": "De GitHub-koppeling is niet (meer) geautoriseerd. Autoriseer de credential opnieuw.",
    "unsupported": "Dit platform ondersteunt GitHub OAuth voor plugins nog niet. Gebruik een personal access token.",
    "invalid_identity": "Er is voor deze uitvoering geen gebruiker bekend. Kies een teamcredential.",
    "no_scope": "Er is voor deze uitvoering geen team bekend.",
}
GEEN_KOPPELING = "Je hebt nog geen GitHub-koppeling. Voeg die toe bij je persoonlijke credentials."


async def _per_code(ctx: NodeContext, referentie: str, soorten):
    """A team credential with this code first, then a fixed personal one; per mode each accepted type in turn.

    The platform checks the type before it decrypts anything, so trying a type reveals nothing.
    """
    verkeerd_type = None
    for modus in ("team", "personal"):
        for type_naam, veld, oauth2 in soorten:
            try:
                return await ctx.credentials.resolve(referentie, mode=modus, expected_type=type_naam,
                                                     oauth2=oauth2), veld
            except CapabilityError as fout:
                if fout.code == "not_found":
                    break  # no credential with this code in this mode, whatever its type
                if fout.code != "wrong_type":
                    raise
                verkeerd_type = fout
    raise verkeerd_type or CapabilityError("credentials", "no credential with this code", code="not_found")


async def autorisatie(ctx: NodeContext, provider: str, referentie: str) -> dict[str, str]:
    """The Authorization header for the selected credential; the value itself is never returned or logged.

    A code selects a Secret with a personal access token, or on GitHub also a GitHub (OAuth) credential.
    ``@user:githubOAuth2Api`` selects the GitHub credential of the person the flow runs for.
    """
    soorten = [(PAT_TYPE, PAT_FIELD, False)]
    if provider == "github":
        soorten.append((GITHUB_OAUTH_TYPE, OAUTH_FIELD, True))
    aanroeper = referentie.startswith(USER_PREFIX)
    try:
        if aanroeper:
            if provider != "github" or referentie != USER_PREFIX + GITHUB_OAUTH_TYPE:
                raise NodeInputError(WEIGERING["wrong_type"])
            credential = await ctx.credentials.resolve(GITHUB_OAUTH_TYPE, mode="personal_type",
                                                       expected_type=GITHUB_OAUTH_TYPE, oauth2=True)
            veld = OAUTH_FIELD
        else:
            credential, veld = await _per_code(ctx, referentie, soorten)
    except CapabilityError as fout:
        if fout.code == "not_found" and aanroeper:
            raise NodeInputError(GEEN_KOPPELING) from None
        if fout.code in WEIGERING:
            raise NodeInputError(WEIGERING[fout.code]) from None
        raise
    waarde = credential.values.get(veld)
    if not isinstance(waarde, str) or not waarde.strip():
        raise NodeInputError(f"The selected credential has no {veld} value")
    waarde = waarde.strip()
    if provider == "azure_devops":  # an Azure DevOps PAT is sent as Basic auth with an empty user name
        return {"Authorization": "Basic " + base64.b64encode((":" + waarde).encode()).decode()}
    return {"Authorization": "Bearer " + waarde}


class AzureDevOps:
    naam = "Azure DevOps"

    def __init__(self, ctx: NodeContext, headers: dict[str, str], organisatie: str, project: str):
        self.ctx = ctx
        self.headers = headers
        self.basis = f"https://dev.azure.com/{seg(organisatie)}/{seg(project)}/_apis/git/repositories"
        self.omschrijving = f"Azure DevOps {organisatie}/{project}"

    def _repo(self, repo: str) -> str:
        return f"{self.basis}/{seg(repo)}"

    async def _get(self, url, params=None):
        query = {**(params or {}), "api-version": AZURE_API_VERSION}
        for poging in range(3):
            antwoord = await self.ctx.http.request("GET", url, headers=self.headers, params=query, timeout=60)
            if antwoord.status in RETRY_STATUS and poging < 2:
                await asyncio.sleep(2 * (poging + 1))
                continue
            # Azure DevOps answers an invalid PAT with 203 and an HTML sign-in page instead of 401.
            if antwoord.status in AZURE_DENIED:
                raise NodeInputError("Azure DevOps weigert de toegang: de credential is ongeldig, verlopen of mist "
                                     "Code (Read).")
            if antwoord.status == 404:
                raise NodeInputError(f"Niet gevonden in Azure DevOps: {url}")
            if not 200 <= antwoord.status < 300:
                raise NodeInputError(f"Azure DevOps gaf HTTP {antwoord.status}")
            return antwoord
        raise NodeInputError(f"Azure DevOps bleef onbereikbaar: {url}")

    async def _refs(self, repo, filter_waarde):
        gevonden = []
        vervolg = None
        for _ in range(MAX_REF_PAGES):
            params = {"filter": filter_waarde, "$top": 1000}
            if vervolg:
                params["continuationToken"] = vervolg
            antwoord = await self._get(f"{self._repo(repo)}/refs", params)
            for ref in json_van(antwoord, "Azure DevOps").get("value", []):
                naam, object_id = str(ref.get("name", "")), ref.get("objectId")
                if naam.startswith("refs/heads/") and object_id:
                    gevonden.append((naam.removeprefix("refs/heads/"), object_id))
            vervolg = antwoord.header("x-ms-continuationtoken")
            if not vervolg:
                break
        return gevonden

    async def git_flow_branches(self, repo):
        gevonden = []
        for prefix in GIT_FLOW:
            gevonden += await self._refs(repo, "heads/" + prefix)
        return gevonden

    async def standaard_branch(self, repo):
        info = json_van(await self._get(self._repo(repo)), "Azure DevOps")
        naam = str(info.get("defaultBranch") or "").removeprefix("refs/heads/")
        if not naam:
            return None  # an empty repository has no default branch
        return next(((b, c) for b, c in await self._refs(repo, "heads/" + naam) if b == naam), None)

    async def bestanden(self, repo, commit):
        commit_info = json_van(await self._get(f"{self._repo(repo)}/commits/{seg(commit)}"), "Azure DevOps")
        boom = json_van(await self._get(f"{self._repo(repo)}/trees/{seg(commit_info['treeId'])}",
                                        {"recursive": "true"}), "Azure DevOps")
        return [(str(e.get("relativePath", "")), e["objectId"], e.get("size"))
                for e in boom.get("treeEntries", []) if e.get("gitObjectType") == "blob" and e.get("objectId")], False

    async def lees(self, repo, object_id):
        antwoord = await self._get(f"{self._repo(repo)}/blobs/{seg(object_id)}", {"$format": "octetstream"})
        return antwoord.body


class GitHub:
    naam = "GitHub"

    def __init__(self, ctx: NodeContext, headers: dict[str, str], eigenaar: str):
        self.ctx = ctx
        self.headers = {**headers, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                        "User-Agent": USER_AGENT}
        self.eigenaar = eigenaar
        self.omschrijving = f"GitHub {eigenaar}"

    def _repo(self, repo: str) -> str:
        """`name` uses the configured owner; `owner/name` overrides it."""
        eigenaar, _, naam = repo.rpartition("/")
        return f"{GITHUB_API}/repos/{seg(eigenaar or self.eigenaar)}/{seg(naam)}"

    async def _get(self, url, params=None, ontbreken_mag=False):
        for poging in range(3):
            antwoord = await self.ctx.http.request("GET", url, headers=self.headers, params=params, timeout=60)
            limiet = antwoord.status == 429 or (
                antwoord.status == 403
                and (antwoord.header("x-ratelimit-remaining") == "0" or antwoord.header("retry-after") is not None))
            if (antwoord.status in RETRY_STATUS or limiet) and poging < 2 and antwoord.header(
                    "x-ratelimit-remaining") != "0":
                await asyncio.sleep(2 * (poging + 1))
                continue
            if antwoord.status == 401:
                raise NodeInputError("GitHub weigert het token: het is ongeldig of verlopen.")
            if limiet:
                raise NodeInputError("GitHub-limiet voor API-verzoeken bereikt; probeer het later opnieuw.")
            if antwoord.status == 403:
                raise NodeInputError("GitHub weigert de toegang: het token mist Contents (Read) of heeft geen "
                                     "toegang tot de repository.")
            if antwoord.status in (404, 409) and ontbreken_mag:
                return None  # 409: the repository is empty
            if antwoord.status == 404:
                raise NodeInputError(f"Niet gevonden op GitHub (of geen toegang): {url.removeprefix(GITHUB_API)}")
            if not 200 <= antwoord.status < 300:
                raise NodeInputError(f"GitHub gaf HTTP {antwoord.status}")
            return antwoord
        raise NodeInputError(f"GitHub bleef onbereikbaar: {url.removeprefix(GITHUB_API)}")

    async def git_flow_branches(self, repo):
        gevonden = []
        for prefix in GIT_FLOW:
            url = f"{self._repo(repo)}/git/matching-refs/heads/{seg(prefix, safe='/')}"
            for _ in range(MAX_REF_PAGES):
                antwoord = await self._get(url, ontbreken_mag=True)
                if antwoord is None:
                    break
                refs = json_van(antwoord, "GitHub")
                for ref in refs if isinstance(refs, list) else []:
                    if not isinstance(ref, dict):
                        continue
                    naam, doel = str(ref.get("ref", "")), ref.get("object") or {}
                    if naam.startswith("refs/heads/") and doel.get("type") == "commit" and doel.get("sha"):
                        gevonden.append((naam.removeprefix("refs/heads/"), doel["sha"]))
                volgende = LINK_NEXT.search(antwoord.header("link") or "")
                if not volgende or not volgende.group(1).startswith(GITHUB_API + "/"):
                    break
                url = volgende.group(1)
        return gevonden

    async def standaard_branch(self, repo):
        info = json_van(await self._get(self._repo(repo)), "GitHub")
        naam = str(info.get("default_branch") or "")
        if not naam:
            return None
        ref = await self._get(f"{self._repo(repo)}/git/ref/heads/{seg(naam, safe='/')}", ontbreken_mag=True)
        doel = (json_van(ref, "GitHub").get("object") or {}) if ref is not None else {}
        return (naam, doel["sha"]) if doel.get("type") == "commit" and doel.get("sha") else None

    async def bestanden(self, repo, commit):
        boom = json_van(await self._get(f"{self._repo(repo)}/git/trees/{seg(commit)}", {"recursive": "1"}), "GitHub")
        entries = [(str(e.get("path", "")), e["sha"], e.get("size"))
                   for e in boom.get("tree") or [] if e.get("type") == "blob" and e.get("sha")]
        return entries, bool(boom.get("truncated"))

    async def lees(self, repo, object_id):
        blob = json_van(await self._get(f"{self._repo(repo)}/git/blobs/{seg(object_id)}"), "GitHub")
        if blob.get("encoding") != "base64":
            raise NodeInputError("GitHub gaf een blob zonder base64-inhoud terug")
        return base64.b64decode(str(blob.get("content") or ""))
