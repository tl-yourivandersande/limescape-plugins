"""Read-only package scanner for Azure DevOps and GitHub repositories.

For each configured repository the newest develop/release/hotfix branch per release line, and optionally the default
branch, is read (refs -> recursive tree -> files). Dependency files of the selected package types (NuGet, npm, PyPI,
Go, Maven, Composer, RubyGems, Cargo) are parsed. The node reports the direct dependencies per release line with their
newest stable versions, and the OSV.dev advisories that affect any dependency in use, transitive ones included.
It only performs read-only requests and never returns credential values.
"""

import asyncio
import re
import time
from datetime import datetime
from typing import Any

from limescape_plugin_sdk import NodeContext, NodeInput, NodeInputError

from ._bronnen import AzureDevOps, GitHub, autorisatie
from ._ecosystemen import ALTIJD_OVERSLAAN, ECOSYSTEMEN, canoniek, ecosysteem_code, herken, pypi_naam, sleutel
from ._gedeeld import alle, decodeer
from ._registers import (
    RANG_LABEL,
    SEVERITY_RANG,
    gefixt_in,
    nieuwste_versies,
    ontdubbel,
    osv_advisories,
    osv_details,
    samenvatting,
    severity,
)

MAX_REPOSITORIES = 10
MAX_RELEASE_LINES = 50
MAX_PROJECT_FILES = 3000
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_LATEST = 300
MAX_ADVISORIES = 1000
MAX_DEPENDENCIES = 20000
SOURCE_CONCURRENCY = 16
DEFAULT_EXCLUDE_PATHS = "sandbox, loadtest, .test/, .tests/, .test., .tests., /testing/"
PROVIDERS = {"azure_devops": "Azure DevOps", "github": "GitHub"}

VERSIE_RE = re.compile(r"^([0-9]+)(\.[0-9]+){1,4}(-RC[0-9]+(\.[0-9]+)?)?$", re.I)


# ---------------------------------------------------------------- parameters

def _param(inp: NodeInput, name: str, default=None):
    value = inp.input_data.get(name)
    return value if value not in (None, "") else inp.param(name, default)


def _required(inp: NodeInput, name: str) -> str:
    value = _param(inp, name)
    if not isinstance(value, str) or not value.strip():
        raise NodeInputError(f"{name} is required")
    return value.strip()


def _optional_int(inp: NodeInput, name: str, default, low: int, high: int):
    value = _param(inp, name, default)
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise NodeInputError(f"{name} must be a whole number") from exc
    if not low <= number <= high:
        raise NodeInputError(f"{name} must be between {low} and {high}")
    return number


def lijst(waarde):
    if waarde is None:
        return []
    if isinstance(waarde, str):
        return [deel.strip() for deel in waarde.split(",") if deel.strip()]
    if isinstance(waarde, (list, tuple, set)):
        return [str(deel).strip() for deel in waarde if str(deel).strip()]
    return [str(waarde).strip()]


def ja(waarde):
    if isinstance(waarde, bool):
        return waarde
    return str(waarde or "").strip().lower() in ("true", "1", "ja", "yes")


def _bron(ctx: NodeContext, inp: NodeInput, provider: str, headers: dict[str, str]):
    organisatie = _required(inp, "organization")
    if provider == "github":
        return GitHub(ctx, headers, organisatie)
    return AzureDevOps(ctx, headers, organisatie, _required(inp, "project"))


async def _headers(ctx: NodeContext, inp: NodeInput, provider: str) -> dict[str, str]:
    reference = _param(inp, "credential_code")
    if not isinstance(reference, str) or not reference.strip():
        raise NodeInputError(f"Select the team credential with the {PROVIDERS[provider]} personal access token")
    return await autorisatie(ctx, provider, reference.strip())


def _ecosystemen(inp: NodeInput) -> list[str]:
    gekozen = []
    for item in lijst(_param(inp, "ecosystems")):
        code = ecosysteem_code(item)
        if code is None:
            raise NodeInputError(f"Unknown package type '{item}'; choose from {', '.join(ECOSYSTEMEN)}")
        gekozen.append(code)
    return [code for code in ECOSYSTEMEN if code in gekozen] or list(ECOSYSTEMEN)


# ---------------------------------------------------------------- versions and branches

def _int(waarde):
    try:
        return int(waarde)
    except (TypeError, ValueError):
        return 0


def sort_key(versie):
    """The default branch first, then develop; release versions numerically, a release candidate before its final."""
    if versie == "develop":
        return (1, (), 0)
    if not VERSIE_RE.match(versie):
        return (2, (), 0)
    nummer, _, kandidaat = versie.partition("-")
    delen = tuple(_int(deel) for deel in nummer.split("."))
    rc = re.search(r"(\d+)", kandidaat)
    return (0, delen + (0,) * (5 - len(delen)), (int(rc.group(1)) if rc else 0) if kandidaat else 10**9)


def release_lijn(versie):
    segmenten = versie.split("-", 1)[0].split(".")
    return f"{segmenten[0]}.{segmenten[1]}" if len(segmenten) >= 2 else segmenten[0]


def lijn_van(versie):
    """develop and the default branch are their own line; a release version belongs to its major.minor line."""
    return release_lijn(versie) if VERSIE_RE.match(versie) else versie


def product_versie(branch, min_major, max_major):
    """develop, or the version of a release/hotfix branch within the major range; otherwise None."""
    if branch == "develop":
        return "develop"
    match = re.match(r"^(release|hotfix)/(.+)$", branch)
    if not match:
        return None
    versie = match.group(2)
    versie_match = VERSIE_RE.match(versie)
    if not versie_match:
        return None
    major = int(versie_match.group(1))
    if major < min_major or (max_major is not None and major > max_major):
        return None
    return versie


def uitgesloten_pad(pad, fragmenten):
    pad = "/" + pad.lower()
    return any(fragment in pad for fragment in fragmenten)


def cel(waarde):
    return str(waarde or "").replace(" ", " ").replace("|", "\\|")


# ---------------------------------------------------------------- scan one repository

async def _scan_repo(bron, repo, instellingen, waarschuwingen):
    """Per release line the newest branch of this repository and the dependencies in its dependency files.

    Returns (scanned lines, {(line, ecosystem, package, version): direct}, statistics).
    """
    min_major, max_major, gekozen_lijnen, uitsluiten, ecosystemen, met_standaard = instellingen
    per_versie: dict[str, list[tuple[str, str]]] = {}
    for branch, commit in await bron.git_flow_branches(repo):
        versie = product_versie(branch, min_major, max_major)
        if versie:
            per_versie.setdefault(versie, []).append((branch, commit))
    if met_standaard:
        standaard = await bron.standaard_branch(repo)
        # develop and release/hotfix branches are already covered (or deliberately outside the major range)
        if standaard and standaard[0] != "develop" and not re.match(r"^(release|hotfix)/", standaard[0]):
            per_versie.setdefault(standaard[0], []).append(standaard)
    per_lijn: dict[str, str] = {}
    for versie in per_versie:
        lijn = lijn_van(versie)
        if gekozen_lijnen and lijn not in gekozen_lijnen:
            continue
        if lijn not in per_lijn or sort_key(versie) > sort_key(per_lijn[lijn]):
            per_lijn[lijn] = versie
    if len(per_lijn) > MAX_RELEASE_LINES:
        waarschuwingen.append(f"{repo}: {len(per_lijn)} release-lijnen, alleen de nieuwste {MAX_RELEASE_LINES} gescand")
        nieuwste = sorted(per_lijn, key=lambda lijn: sort_key(per_lijn[lijn]), reverse=True)[:MAX_RELEASE_LINES]
        per_lijn = {lijn: per_lijn[lijn] for lijn in nieuwste}

    semafoor = asyncio.Semaphore(SOURCE_CONCURRENCY)

    async def begrensd(coroutine):
        async with semafoor:
            return await coroutine

    doelen = [(lijn, branch, commit) for lijn, versie in per_lijn.items() for branch, commit in per_versie[versie]]
    bomen = await alle(begrensd(bron.bestanden(repo, commit)) for *_, commit in doelen)

    nodig: dict[str, tuple[str, str, Any]] = {}  # object id -> (path, ecosystem, parser)
    te_groot: set[str] = set()
    for (_, branch, _), (entries, afgekapt) in zip(doelen, bomen, strict=True):
        if afgekapt:
            waarschuwingen.append(f"{repo}: bestandsboom van {branch} is afgekapt; niet alle bestanden zijn gescand")
        for pad, object_id, grootte in entries:
            herkend = herken(pad)
            if not herkend or herkend[0] not in ecosystemen:
                continue
            if uitgesloten_pad(pad, uitsluiten) or uitgesloten_pad(pad, ALTIJD_OVERSLAAN):
                continue
            if isinstance(grootte, int) and grootte > MAX_FILE_BYTES:
                te_groot.add(pad)
                continue
            nodig[object_id] = (pad, *herkend)
    waarschuwingen += [f"{repo}: {pad} overgeslagen (groter dan 20 MB)" for pad in sorted(te_groot)]
    if len(nodig) > MAX_PROJECT_FILES:
        waarschuwingen.append(f"{repo}: {len(nodig)} dependency-bestanden, alleen de eerste {MAX_PROJECT_FILES} "
                              "gelezen")
        nodig = dict(sorted(nodig.items(), key=lambda item: item[1][0])[:MAX_PROJECT_FILES])

    async def ophalen(object_id):
        pad, eco, parser = nodig[object_id]
        try:
            data = await begrensd(bron.lees(repo, object_id))
        except Exception as fout:  # one unreadable file must not fail the whole scan
            waarschuwingen.append(f"{repo}: {pad} niet gelezen ({type(fout).__name__})")
            return object_id, None
        if len(data) > MAX_FILE_BYTES:
            waarschuwingen.append(f"{repo}: {pad} overgeslagen (groter dan 20 MB)")
            return object_id, None
        try:
            return object_id, parser(decodeer(data))
        except Exception as fout:  # a malformed file only degrades the report
            waarschuwingen.append(f"{repo}: {pad} niet te lezen als {eco}-bestand ({type(fout).__name__})")
            return object_id, None

    gelezen = {oid: inhoud for oid, inhoud in await asyncio.gather(*(ophalen(oid) for oid in nodig))
               if inhoud is not None}

    packages: dict[tuple[str, str, str, str], bool] = {}
    for (lijn, _, _), (entries, _) in zip(doelen, bomen, strict=True):
        direct_namen: set[tuple[str, str]] = set()
        gevonden: list[tuple[str, str, str, bool]] = []
        for _, object_id, _ in entries:
            if object_id not in gelezen:
                continue
            eco = nodig[object_id][1]
            for naam, versie, direct in gelezen[object_id]:
                if direct:
                    direct_namen.add((eco, sleutel(eco, naam)))
                if versie:
                    gevonden.append((eco, naam, versie, direct))
        for eco, naam, versie, direct in gevonden:
            # a lockfile without direct markers is completed by the manifests of the same branch
            sleutel_lijn = (lijn, eco, canoniek(eco, naam), versie)
            packages[sleutel_lijn] = packages.get(sleutel_lijn, False) or direct or (
                (eco, sleutel(eco, naam)) in direct_namen)

    gescand = {lijn: {"versie": versie, "branches": sorted(b for b, _ in per_versie[versie])}
               for lijn, versie in per_lijn.items()}
    statistiek = {"branches": len(doelen), "projectbestanden": len(nodig), "gelezen": len(gelezen)}
    return gescand, packages, statistiek


# ---------------------------------------------------------------- markdown

def _in_gebruik_cel(per_repo):
    if len(set(per_repo.values())) == 1:
        return next(iter(per_repo.values()))
    return "<br>".join(f"{repo}: {versies}" for repo, versies in per_repo.items())


def packages_tabel(release, gecontroleerd, nieuwste):
    regels = [
        f"_Directe dependencies in release {release['versie']}, gecontroleerd op {gecontroleerd}. 'Nieuwste' is de "
        "laatst gepubliceerde stabiele versie in het publieke register._",
        "",
        "|Soort|Package|In gebruik|Nieuwste|Datum|",
        "|--|--|--|--|--|",
    ]
    for eco, pakketten in release["packages"].items():
        for package, per_repo in pakketten.items():
            feed = (nieuwste.get(eco) or {}).get(package) or {}
            regels.append(f"|{eco}|{cel(package)}|{cel(_in_gebruik_cel(per_repo))}|{cel(feed.get('nieuwste') or '-')}|"
                          f"{feed.get('datum', '')}|")
    return "\n".join(regels) + "\n"


def kwetsbaarheden_rapport(releases, gecontroleerd, repos):
    regels = [
        "# Kwetsbaarheden in gebruikte packages",
        "",
        f"_Gecontroleerd op {gecontroleerd} via OSV.dev (api.osv.dev). Alle dependencies van {', '.join(repos)}, ook "
        "transitieve uit lockfiles, per release-lijn (nieuwste patch/hotfix per repo)._",
        "_Alleen advisories die de daadwerkelijk gebruikte versie raken worden getoond. Uitgesloten paden en packages "
        "tellen niet mee._",
        "",
        "## Samenvatting",
        "",
        "|Release|Versie|Kwetsbare packages|Hoogste severity|",
        "|--|--|--|--|",
    ]
    for release in releases:
        regels.append(f"|{release['release_lijn']}|{release['versie']}|{release['aantal_kwetsbare_packages']}|"
                      f"{release['hoogste_severity']}|")
    regels += ["", "## Details per release", ""]
    details = False
    for release in releases:
        if not release["kwetsbaarheden"]:
            continue
        details = True
        regels += [f"### {release['release_lijn']}  ({release['versie']})", "",
                   "|Soort|Package|Direct|Versie in gebruik|Severity|Advisory|Gefixt in|Samenvatting|",
                   "|--|--|--|--|--|--|--|--|"]
        for rij in release["kwetsbaarheden"]:
            advisory = f"[{rij['advisory']}](https://osv.dev/vulnerability/{rij['advisory']})"
            if rij["cve"]:
                advisory += f" ({rij['cve']})"
            tekst = cel(rij["samenvatting"]).replace("\r", " ").replace("\n", " ")
            regels.append(f"|{rij['ecosystem']}|{cel(rij['package'])}|{'ja' if rij['direct'] else 'nee'}|"
                          f"{rij['repo']} {rij['versie']}|{rij['severity']}|{advisory}|{rij['gefixt_in'] or '-'}|"
                          f"{tekst}|")
        regels.append("")
    if not details:
        regels.append("_Geen kwetsbaarheden gevonden in de gebruikte versies._")
    return "\n".join(regels) + "\n"


# ---------------------------------------------------------------- execute

def _kwetsbaarheden(repos, per_repo, lijn, gekozen, advisories):
    rijen = []
    for repo in repos:
        for (lj, eco, package, versie), direct in sorted(per_repo[repo][1].items()):
            if lj != lijn:
                continue
            for advisory_id, cves in gekozen.get((eco, package, versie), []):
                advisory = advisories[advisory_id]
                rijen.append({
                    "ecosystem": eco, "package": package, "repo": repo, "versie": versie, "direct": direct,
                    "severity": severity(advisory) or "onbekend", "advisory": advisory_id, "cve": ", ".join(cves),
                    "gefixt_in": gefixt_in(advisory, eco, package), "samenvatting": samenvatting(advisory),
                })
    rijen.sort(key=lambda r: (-SEVERITY_RANG.get(r["severity"], 0), not r["direct"], r["ecosystem"], r["package"]))
    return rijen


def _nieuwste_doelen(gevolgd, per_repo, ecosystemen, waarschuwingen):
    """(ecosystem, package) pairs to look up: the direct dependencies, or the configured list.

    A configured name may carry a package-type prefix (`pypi:requests`); a bare name is looked up in the package
    types where the scan found it, or in the only selected package type.
    """
    gevonden: dict[tuple[str, str], tuple[str, str]] = {}
    direct: dict[tuple[str, str], tuple[str, str]] = {}
    for _, packages, _ in per_repo.values():
        for (_, eco, package, _), is_direct in sorted(packages.items()):
            gevonden.setdefault((eco, sleutel(eco, package)), (eco, package))
            if is_direct:
                direct.setdefault((eco, sleutel(eco, package)), (eco, package))
    if not gevolgd:
        return sorted(direct.values(), key=lambda paar: (list(ECOSYSTEMEN).index(paar[0]), paar[1].lower()))
    doelen: list[tuple[str, str]] = []
    for item in gevolgd:
        prefix, _, rest = item.partition(":")
        eco_prefix = ecosysteem_code(prefix) if rest else None
        if eco_prefix:
            doelen.append(gevonden.get((eco_prefix, sleutel(eco_prefix, rest)), (eco_prefix, rest)))
            continue
        treffers = [paar for (eco, naam), paar in gevonden.items() if naam == sleutel(eco, item)]
        if treffers:
            doelen += treffers
        elif len(ecosystemen) == 1:
            doelen.append((ecosystemen[0], canoniek(ecosystemen[0], item)))
        else:
            waarschuwingen.append(f"{item} niet gevonden in de scan; geef de soort op, bijvoorbeeld npm:{item}")
    return list(dict.fromkeys(doelen))


async def execute(ctx: NodeContext, inp: NodeInput):
    try:
        begin = time.monotonic()
        provider = str(_param(inp, "provider", "azure_devops") or "azure_devops").strip().lower()
        if provider not in PROVIDERS:
            raise NodeInputError("provider must be azure_devops or github")
        headers = await _headers(ctx, inp, provider)
        bron = _bron(ctx, inp, provider, headers)
        repos = list(dict.fromkeys(lijst(_param(inp, "repositories"))))
        if not repos:
            raise NodeInputError("repositories is required")
        if len(repos) > MAX_REPOSITORIES:
            raise NodeInputError(f"At most {MAX_REPOSITORIES} repositories can be scanned at once")
        ecosystemen = _ecosystemen(inp)
        min_major = _optional_int(inp, "min_major", 0, 0, 100000) or 0
        max_major = _optional_int(inp, "max_major", None, 0, 100000)
        if max_major is not None and max_major < min_major:
            raise NodeInputError("max_major must be at least min_major")
        onderdelen = str(_param(inp, "onderdelen", "alles") or "alles").strip().lower()
        if onderdelen not in {"alles", "componenten", "kwetsbaarheden"}:
            raise NodeInputError("onderdelen must be alles, componenten, or kwetsbaarheden")
        gevraagd = _param(inp, "release_lines") or _param(inp, "release_lijnen")
        gekozen_lijnen = {release_lijn(x) if x[:1].isdigit() else x for x in lijst(gevraagd)}
        met_standaard = ja(_param(inp, "include_default_branch", True))
        uitsluiten = [deel.lower() for deel in lijst(_param(inp, "exclude_paths", DEFAULT_EXCLUDE_PATHS))]
        uitgesloten_packages = {deel.lower() for deel in lijst(_param(inp, "exclude_packages"))}
        uitgesloten_sleutels = uitgesloten_packages | {pypi_naam(deel) for deel in uitgesloten_packages}
        gevolgd = list(dict.fromkeys(lijst(_param(inp, "latest_packages"))))
        met_markdown = ja(_param(inp, "markdown", False))
        vandaag = datetime.now()
        gecontroleerd = f"{vandaag.day}-{vandaag.month}-{vandaag.year}"
        waarschuwingen: list[str] = []

        instellingen = (min_major, max_major, gekozen_lijnen, uitsluiten, set(ecosystemen), met_standaard)
        resultaten = await alle(_scan_repo(bron, repo, instellingen, waarschuwingen) for repo in repos)
        per_repo = {
            repo: (gescand, {k: d for k, d in packages.items() if sleutel(k[1], k[2]) not in uitgesloten_sleutels},
                   statistiek)
            for repo, (gescand, packages, statistiek) in zip(repos, resultaten, strict=True)
        }
        for _, repo_packages, repo_statistiek in per_repo.values():
            repo_statistiek["dependencies"] = len({k[1:] for k in repo_packages})
            repo_statistiek["direct"] = len({k[1:] for k, direct in repo_packages.items() if direct})

        lijnen_versie: dict[str, str] = {}
        for repo in repos:
            for lijn, info in per_repo[repo][0].items():
                if lijn not in lijnen_versie or sort_key(info["versie"]) > sort_key(lijnen_versie[lijn]):
                    lijnen_versie[lijn] = info["versie"]
        volgorde = sorted(lijnen_versie, key=lambda x: sort_key(lijnen_versie[x]), reverse=True)

        nieuwste: dict[str, Any] = {}
        if onderdelen in ("alles", "componenten"):
            doelen = _nieuwste_doelen(gevolgd, per_repo, ecosystemen, waarschuwingen)
            if len(doelen) > MAX_LATEST:
                waarschuwingen.append(f"{len(doelen)} packages voor de nieuwste versie, alleen de eerste {MAX_LATEST} "
                                      "opgezocht")
                doelen = doelen[:MAX_LATEST]
            nieuwste = await nieuwste_versies(ctx, doelen, waarschuwingen)

        advisories: dict[str, Any] = {}
        gekozen: dict[tuple[str, str, str], list[tuple[str, list[str]]]] = {}
        if onderdelen in ("alles", "kwetsbaarheden"):
            drietallen = sorted({k[1:] for repo in repos for k in per_repo[repo][1]})
            if len(drietallen) > MAX_DEPENDENCIES:
                waarschuwingen.append(f"{len(drietallen)} dependencies, alleen de eerste {MAX_DEPENDENCIES} "
                                      "gecontroleerd op kwetsbaarheden")
                drietallen = drietallen[:MAX_DEPENDENCIES]
            per_drietal = await osv_advisories(ctx, drietallen)
            ids = sorted({advisory_id for lijst_ids in per_drietal.values() for advisory_id in lijst_ids})
            advisories = await osv_details(ctx, ids, MAX_ADVISORIES, waarschuwingen)
            gekozen = {drietal: ontdubbel(ids, advisories) for drietal, ids in per_drietal.items() if ids}

        releases = []
        for lijn in volgorde:
            in_gebruik: dict[str, dict[str, dict[str, set[str]]]] = {}
            for repo in repos:
                for (lj, eco, package, versie), direct in per_repo[repo][1].items():
                    if lj == lijn and direct:
                        in_gebruik.setdefault(eco, {}).setdefault(package, {}).setdefault(repo, set()).add(versie)
            packages = {
                eco: {package: {repo: " / ".join(sorted(v)) for repo, v in in_gebruik[eco][package].items()}
                      for package in sorted(in_gebruik[eco], key=str.lower)}
                for eco in ECOSYSTEMEN if eco in in_gebruik
            }
            rijen = _kwetsbaarheden(repos, per_repo, lijn, gekozen, advisories)
            hoogste = max((SEVERITY_RANG.get(r["severity"], 0) for r in rijen), default=0)
            release: dict[str, Any] = {
                "release_lijn": lijn,
                "versie": lijnen_versie[lijn],
                "branches": {repo: per_repo[repo][0][lijn]["branches"] for repo in repos if lijn in per_repo[repo][0]},
            }
            if onderdelen != "kwetsbaarheden":
                release["packages"] = packages
            if onderdelen != "componenten":
                release["aantal_kwetsbare_packages"] = len({(r["ecosystem"], r["package"], r["versie"])
                                                            for r in rijen})
                release["hoogste_severity"] = RANG_LABEL[hoogste]
                release["kwetsbaarheden"] = rijen
            releases.append(release)

        statistiek: dict[str, Any] = {repo: per_repo[repo][2] for repo in repos}
        resultaat: dict[str, Any] = {
            "gecontroleerd_op": gecontroleerd,
            "onderdelen": onderdelen,
            "bron": f"{bron.omschrijving}: " + ", ".join(repos),
            "ecosystemen": ecosystemen,
            "uitgesloten_packages": sorted(uitgesloten_packages),
            "uitgesloten_paden": uitsluiten,
            "nieuwste_versies": nieuwste or None,
            "releases": releases,
            "statistiek": statistiek,
            "waarschuwingen": waarschuwingen,
        }
        if met_markdown:
            markdown: dict[str, Any] = {}
            if onderdelen in ("alles", "componenten"):
                markdown["packages_per_release"] = {r["release_lijn"]: packages_tabel(r, gecontroleerd, nieuwste)
                                                    for r in releases}
            if onderdelen in ("alles", "kwetsbaarheden"):
                markdown["kwetsbaarheden"] = kwetsbaarheden_rapport(releases, gecontroleerd, repos)
            resultaat["markdown"] = markdown

        statistiek["duur_seconden"] = round(time.monotonic() - begin, 1)
        ctx.trace.event("package_scan", {"release_lijnen": len(releases), "waarschuwingen": len(waarschuwingen)})
        yield {inp.output_key: resultaat}
    except NodeInputError as exc:
        yield {inp.output_key: {"error": str(exc)}}
    except Exception:
        message = "Package scan failed; check credentials, permissions, and service availability"
        yield {inp.output_key: {"error": message}}
