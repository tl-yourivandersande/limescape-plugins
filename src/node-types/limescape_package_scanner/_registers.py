"""Public package registries and OSV.dev. These requests are anonymous and never receive the source credential.

Newest versions come from deps.dev (NuGet, npm, PyPI, Go, Maven, RubyGems, Cargo) and packagist.org (Composer).
"""

import asyncio
import re

from limescape_plugin_sdk import NodeInputError

from ._ecosystemen import ECOSYSTEMEN, sleutel
from ._gedeeld import BronFout, datum_nl, json_van, seg

OSV = "https://api.osv.dev/v1"
DEPS_DEV = "https://api.deps.dev/v3/systems"
PACKAGIST = "https://repo.packagist.org/p2"
OSV_BATCH = 1000
PUBLIC_CONCURRENCY = 8
PACKAGIST_NAAM = re.compile(r"^[a-z0-9][a-z0-9_.-]*/[a-z0-9][a-z0-9_.-]*$")
PACKAGIST_PRERELEASE = re.compile(r"(alpha|beta|rc|dev|preview|pre)", re.I)
SEVERITY_RANG = {"CRITICAL": 4, "HIGH": 3, "MODERATE": 2, "MEDIUM": 2, "LOW": 1}
RANG_LABEL = {4: "CRITICAL", 3: "HIGH", 2: "MODERATE", 1: "LOW", 0: "-"}


async def _get(ctx, url):
    antwoord = await ctx.http.request("GET", url, timeout=60)
    if not 200 <= antwoord.status < 300:
        raise BronFout(antwoord.status)
    return antwoord


async def _nieuwste(ctx, eco: str, naam: str) -> tuple[str, str]:
    """Newest stable version and its publication date (dd-mm-yyyy)."""
    if eco == "composer":
        naam = naam.lower()
        if not PACKAGIST_NAAM.match(naam):
            raise BronFout(404)
        data = json_van(await _get(ctx, f"{PACKAGIST}/{seg(naam, safe='/')}.json"), "Packagist")
        versies = [v for v in (data.get("packages") or {}).get(naam) or [] if isinstance(v, dict)]
        stabiel = [v for v in versies if not PACKAGIST_PRERELEASE.search(str(v.get("version", "")))]
        if not (stabiel or versies):
            raise BronFout(404)
        keuze = (stabiel or versies)[0]  # Packagist lists the newest version first
        return str(keuze.get("version")), datum_nl(keuze.get("time"))
    systeem = ECOSYSTEMEN[eco][1]
    data = json_van(await _get(ctx, f"{DEPS_DEV}/{systeem}/packages/{seg(naam)}"), "deps.dev")
    versies = [v for v in data.get("versions") or [] if isinstance(v, dict)]
    standaard: dict | None = next((v for v in versies if v.get("isDefault")), None)  # the registry's default version
    if standaard is None:
        standaard = max(versies, key=lambda v: str(v.get("publishedAt") or ""), default=None)
    if standaard is None:
        raise BronFout(404)
    return str((standaard.get("versionKey") or {}).get("version")), datum_nl(standaard.get("publishedAt"))


async def nieuwste_versies(ctx, doelen: list[tuple[str, str]], waarschuwingen: list[str]):
    """{ecosystem: {package: {nieuwste, datum, status}}} for the given (ecosystem, package) pairs."""
    semafoor = asyncio.Semaphore(PUBLIC_CONCURRENCY)

    async def opzoeken(eco, naam):
        register = ECOSYSTEMEN[eco][2]
        dienst = "packagist.org" if eco == "composer" else "deps.dev"
        async with semafoor:
            try:
                versie, datum = await _nieuwste(ctx, eco, naam)
                return eco, naam, {"nieuwste": versie, "datum": datum, "status": "ok"}
            except BronFout as fout:
                if fout.status == 404:  # e.g. a package from a private feed
                    return eco, naam, {"nieuwste": None, "datum": "", "status": f"niet gevonden op {register}"}
                waarschuwingen.append(f"{dienst} {eco} {naam} niet bereikbaar ({fout})")
            except Exception as fout:  # an unreachable registry only degrades the report
                waarschuwingen.append(f"{dienst} {eco} {naam} niet bereikbaar ({type(fout).__name__})")
            return eco, naam, {"nieuwste": None, "datum": "", "status": "register niet bereikbaar"}

    uit: dict[str, dict[str, dict]] = {}
    for eco, naam, info in await asyncio.gather(*(opzoeken(eco, naam) for eco, naam in doelen)):
        uit.setdefault(eco, {})[naam] = info
    return uit


async def osv_advisories(ctx, drietallen: list[tuple[str, str, str]]):
    """{(ecosystem, package, version): [advisory id, ...]} via the OSV batch query."""
    per_drietal: dict[tuple[str, str, str], list[str]] = {}
    for start in range(0, len(drietallen), OSV_BATCH):
        blok = drietallen[start:start + OSV_BATCH]
        body = {"queries": [{"package": {"ecosystem": ECOSYSTEMEN[eco][0], "name": naam}, "version": versie}
                            for eco, naam, versie in blok]}
        antwoord = await ctx.http.request("POST", f"{OSV}/querybatch", headers={"Content-Type": "application/json"},
                                          json=body, timeout=90)
        if not 200 <= antwoord.status < 300:
            raise NodeInputError(f"OSV.dev gaf HTTP {antwoord.status}")
        for drietal, resultaat in zip(blok, json_van(antwoord, "OSV.dev").get("results", []), strict=False):
            per_drietal[drietal] = [v["id"] for v in (resultaat or {}).get("vulns") or [] if v.get("id")]
    return per_drietal


async def osv_details(ctx, ids: list[str], maximum: int, waarschuwingen: list[str]):
    if len(ids) > maximum:
        waarschuwingen.append(f"{len(ids)} advisories gevonden, alleen de eerste {maximum} opgehaald")
        ids = ids[:maximum]
    semafoor = asyncio.Semaphore(PUBLIC_CONCURRENCY)

    async def detail(advisory_id):
        async with semafoor:
            try:
                return advisory_id, (await _get(ctx, f"{OSV}/vulns/{seg(advisory_id)}")).json()
            except Exception as fout:  # an advisory without details is left out of the report
                reden = str(fout) if isinstance(fout, BronFout) else type(fout).__name__
                waarschuwingen.append(f"OSV-details {advisory_id} niet opgehaald ({reden})")
                return advisory_id, None

    return {aid: data for aid, data in await asyncio.gather(*(detail(i) for i in ids)) if data}


def severity(advisory: dict) -> str:
    return str((advisory.get("database_specific") or {}).get("severity") or "").upper()


def ontdubbel(ids: list[str], advisories: dict) -> list[tuple[str, list[str]]]:
    """One advisory per vulnerability: OSV returns e.g. GO-, PYSEC- or RUSTSEC- records next to the GHSA record of the
    same vulnerability, linked through their aliases. Per group the record with a severity (the GHSA one) is kept.
    Returns [(advisory id, CVE ids of the group)]."""
    groepen: list[tuple[set[str], list[str]]] = []
    for advisory_id in ids:
        data = advisories.get(advisory_id)
        if not data:
            continue
        sleutels = {advisory_id, *(str(a) for a in data.get("aliases") or [])}
        samen = [groep for groep in groepen if groep[0] & sleutels]
        nieuw: tuple[set[str], list[str]] = (sleutels, [advisory_id])
        for groep in samen:
            nieuw[0].update(groep[0])
            nieuw[1].extend(groep[1])
            groepen.remove(groep)
        groepen.append(nieuw)
    gekozen = []
    for sleutels, leden in groepen:
        beste = sorted(leden, key=lambda i: (not severity(advisories[i]), not i.startswith("GHSA-"), i))[0]
        gekozen.append((beste, sorted(s for s in sleutels if s.startswith("CVE-"))))
    return sorted(gekozen)


def gefixt_in(advisory: dict, eco: str, package: str) -> str:
    versies: list[str] = []
    for affected in advisory.get("affected") or []:
        if sleutel(eco, str((affected.get("package") or {}).get("name", ""))) != sleutel(eco, package):
            continue
        for bereik in affected.get("ranges") or []:
            for event in bereik.get("events") or []:
                if event.get("fixed") and event["fixed"] not in versies:
                    versies.append(event["fixed"])
    return ", ".join(versies)


def samenvatting(advisory: dict) -> str:
    tekst = advisory.get("summary") or str(advisory.get("details") or "").strip().split("\n", 1)[0]
    return tekst if len(tekst) <= 200 else tekst[:197] + "..."
