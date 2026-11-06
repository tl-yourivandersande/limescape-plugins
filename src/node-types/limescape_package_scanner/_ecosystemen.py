"""Package ecosystems: which files hold dependencies and how to read them, using the standard library only.

Every parser returns ``[(name, version or None, direct)]``. A version of None comes from a manifest that declares a
dependency without an exact version; it only marks that name as a direct dependency. Lockfiles also list transitive
dependencies (direct False) unless the lockfile itself records which dependencies are direct.
"""

import json
import re
import tomllib

ECOSYSTEMEN = {
    # code: (OSV.dev ecosystem, deps.dev system or None, public registry)
    "nuget": ("NuGet", "nuget", "nuget.org"),
    "npm": ("npm", "npm", "npmjs.com"),
    "pypi": ("PyPI", "pypi", "pypi.org"),
    "go": ("Go", "go", "proxy.golang.org"),
    "maven": ("Maven", "maven", "Maven Central"),
    "composer": ("Packagist", None, "packagist.org"),
    "rubygems": ("RubyGems", "rubygems", "rubygems.org"),
    "cargo": ("crates.io", "cargo", "crates.io"),
}
ALIASSEN = {
    ".net": "nuget", "dotnet": "nuget", "c#": "nuget", "csharp": "nuget",
    "javascript": "npm", "js": "npm", "typescript": "npm", "ts": "npm", "node": "npm", "nodejs": "npm",
    "yarn": "npm", "pnpm": "npm",
    "python": "pypi", "pip": "pypi", "poetry": "pypi", "uv": "pypi",
    "golang": "go", "java": "maven", "php": "composer", "packagist": "composer",
    "ruby": "rubygems", "gem": "rubygems", "gems": "rubygems", "bundler": "rubygems",
    "rust": "cargo", "crates": "cargo", "crates.io": "cargo",
}

Pakket = tuple[str, str | None, bool]


def ecosysteem_code(waarde) -> str | None:
    code = str(waarde).strip().lower()
    code = ALIASSEN.get(code, code)
    return code if code in ECOSYSTEMEN else None


def pypi_naam(naam: str) -> str:
    return re.sub(r"[-_.]+", "-", naam).lower()


def canoniek(eco: str, naam: str) -> str:
    """The name in the report: PyPI names are normalised (PEP 503), other names are kept as written."""
    return pypi_naam(naam) if eco == "pypi" else naam


def sleutel(eco: str, naam: str) -> str:
    """Case-insensitive comparison key for direct-dependency matching, exclusions and lookups."""
    return pypi_naam(naam) if eco == "pypi" else naam.lower()


def _dict(waarde) -> dict:
    return waarde if isinstance(waarde, dict) else {}


def _lijst(waarde) -> list:
    return waarde if isinstance(waarde, list) else []


# ---------------------------------------------------------------- NuGet

NUGET_REGEL = re.compile(r"<PackageReference|<PackageVersion|<package |<Version>")
NUGET_INLINE = re.compile(r'<Package(?:Reference|Version)\s+(?:Include|Update)="([^"]+)"\s+Version="([^"]+)"', re.I)
NUGET_CONFIG = re.compile(r'<package\s+id="([^"]+)"\s+version="([^"]+)"', re.I)
NUGET_OPEN = re.compile(r'<Package(?:Reference|Version)\s+(?:Include|Update)="([^"]+)"', re.I)
NUGET_VERSIE_ATTR = re.compile(r'\sVersion="([^"]+)"', re.I)
NUGET_VERSIE_TAG = re.compile(r"<Version>([^<]+)</Version>", re.I)


def parse_nuget_project(tekst: str) -> list[Pakket]:
    """A .csproj/.fsproj/.vbproj, packages.config or Directory.*.props.

    The two-line form <PackageReference Include="X"> ... <Version>Y</Version> is paired within 4 lines.
    Versions with an MSBuild variable ($(...)) or a wildcard are skipped.
    """
    gevonden = []
    open_package = None
    open_regel = 0
    for nummer, regel in enumerate(tekst.split("\n"), 1):
        if not NUGET_REGEL.search(regel):
            continue
        match = NUGET_INLINE.search(regel) or NUGET_CONFIG.search(regel)
        if match:
            gevonden.append((match.group(1), match.group(2)))
            open_package = None
            continue
        match = NUGET_OPEN.search(regel)
        if match:
            attribuut = NUGET_VERSIE_ATTR.search(regel, match.end())
            if attribuut:
                gevonden.append((match.group(1), attribuut.group(1)))
                open_package = None
            else:
                open_package, open_regel = match.group(1), nummer
            continue
        match = NUGET_VERSIE_TAG.search(regel)
        if match and open_package and nummer - open_regel <= 4:
            gevonden.append((open_package, match.group(1)))
            open_package = None
    return [(naam, versie.strip(), True) for naam, versie in gevonden if not re.search(r"[$*]", versie)]


def parse_nuget_lock(tekst: str) -> list[Pakket]:
    """packages.lock.json: resolved versions per target framework, typed Direct or (Central)Transitive."""
    uit: list[Pakket] = []
    for framework in _dict(_dict(json.loads(tekst)).get("dependencies")).values():
        for naam, info in _dict(framework).items():
            info = _dict(info)
            versie = info.get("resolved")
            if info.get("type") != "Project" and isinstance(versie, str):
                uit.append((naam, versie, info.get("type") == "Direct"))
    return uit


# ---------------------------------------------------------------- npm

NPM_EXACT = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
NPM_DEP_VELDEN = ("dependencies", "devDependencies", "optionalDependencies")
YARN_OVERSLAAN = ("@workspace:", "@link:", "@portal:", "@file:", "@patch:", "@exec:")
YARN_VERSIE = re.compile(r'^ {2}version:?\s+"?([^"\s]+)"?\s*$')
PNPM_SLEUTEL = re.compile(r"""^ {2}['"]?/?((?:@[^/@\s'"]+/)?[^/@\s'"(]+)[@/](\d[^\s'"():_]*)""")


def _npm_naam(sleutel_pad: str) -> str:
    return sleutel_pad.rsplit("node_modules/", 1)[-1]


def parse_npm_lock(tekst: str) -> list[Pakket]:
    """package-lock.json / npm-shrinkwrap.json, lockfileVersion 1 to 3."""
    data = _dict(json.loads(tekst))
    uit: list[Pakket] = []
    pakketten = _dict(data.get("packages"))
    if pakketten:
        direct: set[str] = set()
        for pad, info in pakketten.items():
            if "node_modules/" not in pad:  # the root ("") or a workspace package
                for veld in (*NPM_DEP_VELDEN, "peerDependencies"):
                    direct.update(_dict(_dict(info).get(veld)))
        for pad, info in pakketten.items():
            info = _dict(info)
            versie = info.get("version")
            if "node_modules/" not in pad or info.get("link") or not isinstance(versie, str):
                continue
            alias = info.get("name")  # an npm alias installs the package named here
            naam = alias if isinstance(alias, str) else _npm_naam(pad)
            uit.append((naam, versie, bool(pad.count("node_modules/") == 1 and _npm_naam(pad) in direct)))
        return uit
    stapel = [_dict(data.get("dependencies"))]  # lockfileVersion 1: nested, direct dependencies unknown
    while stapel:
        for naam, info in stapel.pop().items():
            info = _dict(info)
            versie = info.get("version")
            if isinstance(versie, str) and versie[:1].isdigit():
                uit.append((naam, versie, False))
            if info.get("dependencies"):
                stapel.append(_dict(info.get("dependencies")))
    return uit


def parse_package_json(tekst: str) -> list[Pakket]:
    """package.json declares the direct dependencies; only exactly pinned versions are usable as a version."""
    data = _dict(json.loads(tekst))
    uit: list[Pakket] = []
    for veld in NPM_DEP_VELDEN:
        for naam, spec in _dict(data.get(veld)).items():
            versie = spec.strip() if isinstance(spec, str) else ""
            uit.append((naam, versie if NPM_EXACT.match(versie) else None, True))
    return uit


def _yarn_naam(spec: str) -> str:
    spec = spec.strip().strip('"')
    at = spec.find("@", 1)
    return spec[:at] if at > 0 else spec


def parse_yarn_lock(tekst: str) -> list[Pakket]:
    """yarn.lock, both the classic (v1) and the Berry (v2+) format."""
    uit: list[Pakket] = []
    namen: list[str] = []
    for regel in tekst.splitlines():
        if not regel.strip() or regel.lstrip().startswith("#"):
            continue
        if not regel.startswith(" "):
            kop = regel.rstrip().rstrip(":")
            specs = [deel.strip().strip('"') for deel in kop.split(",")]
            namen = [] if kop.startswith(("__metadata", '"__metadata')) else sorted({
                _yarn_naam(spec) for spec in specs if spec and not any(p in spec for p in YARN_OVERSLAAN)})
            continue
        match = YARN_VERSIE.match(regel)
        if match and namen:
            uit += [(naam, match.group(1), False) for naam in namen]
            namen = []
    return uit


def parse_pnpm_lock(tekst: str) -> list[Pakket]:
    """pnpm-lock.yaml (v5 to v9): the keys of the top-level packages section; direct names come from package.json."""
    uit: list[Pakket] = []
    in_packages = False
    for regel in tekst.splitlines():
        if regel[:1] not in ("", " ", "#"):
            in_packages = regel.rstrip() == "packages:"
            continue
        match = PNPM_SLEUTEL.match(regel) if in_packages else None
        if match:
            uit.append((match.group(1), match.group(2), False))
    return uit


# ---------------------------------------------------------------- PyPI

PEP508_NAAM = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
PEP508_EXACT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*===?\s*([0-9][^\s;,#\\]*)")


def _pep508(spec) -> Pakket | None:
    if not isinstance(spec, str):
        return None
    exact = PEP508_EXACT.match(spec)
    if exact:
        return exact.group(1), exact.group(2), True
    naam = PEP508_NAAM.match(spec)
    return (naam.group(1), None, True) if naam else None


def parse_uv_lock(tekst: str) -> list[Pakket]:
    """uv.lock: dependencies of the project's own (editable or virtual) packages are direct."""
    pakketten = [p for p in _lijst(tomllib.loads(tekst).get("package")) if isinstance(p, dict)]
    direct: set[str] = set()
    uit: list[Pakket] = []
    for pakket in pakketten:
        bron = _dict(pakket.get("source"))
        if "editable" in bron or "virtual" in bron:
            deps = list(_lijst(pakket.get("dependencies")))
            for veld in ("optional-dependencies", "dev-dependencies"):
                for groep in _dict(pakket.get(veld)).values():
                    deps += _lijst(groep)
            direct.update(pypi_naam(d["name"]) for d in deps if isinstance(d, dict) and isinstance(d.get("name"), str))
    for pakket in pakketten:
        bron = _dict(pakket.get("source"))
        naam, versie = pakket.get("name"), pakket.get("version")
        if any(k in bron for k in ("editable", "virtual", "path", "directory")):
            continue
        if isinstance(naam, str) and isinstance(versie, str):
            uit.append((naam, versie, pypi_naam(naam) in direct))
    return uit


def parse_poetry_lock(tekst: str) -> list[Pakket]:
    """poetry.lock lists every dependency; direct names come from pyproject.toml."""
    uit: list[Pakket] = []
    for pakket in _lijst(tomllib.loads(tekst).get("package")):
        pakket = _dict(pakket)
        naam, versie = pakket.get("name"), pakket.get("version")
        if _dict(pakket.get("source")).get("type") in ("directory", "file"):
            continue
        if isinstance(naam, str) and isinstance(versie, str):
            uit.append((naam, versie, False))
    return uit


def parse_pipfile_lock(tekst: str) -> list[Pakket]:
    data = _dict(json.loads(tekst))
    uit: list[Pakket] = []
    for sectie in ("default", "develop"):
        for naam, info in _dict(data.get(sectie)).items():
            versie = str(_dict(info).get("version") or "")
            if versie.startswith("=="):
                uit.append((naam, versie[2:], False))
    return uit


def parse_pipfile(tekst: str) -> list[Pakket]:
    data = tomllib.loads(tekst)
    return [(naam, None, True) for sectie in ("packages", "dev-packages") for naam in _dict(data.get(sectie))]


def parse_pyproject(tekst: str) -> list[Pakket]:
    """pyproject.toml: PEP 621 dependencies, dependency groups, uv dev-dependencies and Poetry dependencies."""
    data = tomllib.loads(tekst)
    project = _dict(data.get("project"))
    specs = list(_lijst(project.get("dependencies")))
    for groep in _dict(project.get("optional-dependencies")).values():
        specs += _lijst(groep)
    for groep in _dict(data.get("dependency-groups")).values():
        specs += _lijst(groep)
    tool = _dict(data.get("tool"))
    specs += _lijst(_dict(tool.get("uv")).get("dev-dependencies"))
    uit = [pakket for pakket in map(_pep508, specs) if pakket]
    poetry = _dict(tool.get("poetry"))
    tabellen = [poetry.get("dependencies"), poetry.get("dev-dependencies")]
    tabellen += [_dict(groep).get("dependencies") for groep in _dict(poetry.get("group")).values()]
    uit += [(naam, None, True) for tabel in tabellen for naam in _dict(tabel) if naam.lower() != "python"]
    return uit


def parse_requirements(tekst: str) -> list[Pakket]:
    """requirements*.txt: pinned (==) lines give versions. In pip-compile output a requirement is direct only when
    its "# via" annotation names a -r file; a file without annotations is treated as hand-written (all direct)."""
    regels: list[list] = []  # [name, version or None, has via annotation, via names a -r file]
    in_via = False
    for regel in tekst.splitlines():
        kaal = regel.strip()
        if not kaal:
            in_via = False
            continue
        if kaal.startswith("#"):
            inhoud = kaal.lstrip("#").strip()
            if regels and inhoud.startswith("via"):
                regels[-1][2], in_via = True, True
                regels[-1][3] = regels[-1][3] or inhoud[3:].strip().startswith("-r")
            elif regels and in_via and regel[:1] in (" ", "\t") and inhoud.startswith("-r"):
                regels[-1][3] = True
            continue
        in_via = False
        if kaal.startswith(("-", ".", "/")) or "://" in kaal:
            continue  # options, editable installs, includes, hash lines, local paths and URLs
        pakket = _pep508(kaal)
        if pakket:
            regels.append([pakket[0], pakket[1], False, False])
    return [(naam, versie, not via or via_r) for naam, versie, via, via_r in regels]


# ---------------------------------------------------------------- Go, Maven, Composer, RubyGems, Cargo

GO_REQUIRE = re.compile(r"^(\S+)\s+(v\S+)(.*)$")


def parse_go_mod(tekst: str) -> list[Pakket]:
    """go.mod require directives; `// indirect` marks a transitive dependency."""
    uit: list[Pakket] = []
    in_blok = False
    for regel in tekst.splitlines():
        kaal = regel.strip()
        if re.match(r"^require\s*\($", kaal):
            in_blok = True
            continue
        if in_blok and kaal.startswith(")"):
            in_blok = False
            continue
        if in_blok:
            spec = kaal
        elif kaal.startswith("require "):
            spec = kaal[len("require "):].strip()
        else:
            continue
        match = GO_REQUIRE.match(spec)
        if match:
            uit.append((match.group(1), match.group(2), "// indirect" not in match.group(3)))
    return uit


POM_BLOKKEN = re.compile(r"<(parent|dependencies|dependencyManagement|build|profiles|reporting)>.*?</\1>", re.S)
POM_VARIABELE = re.compile(r"\$\{([^}]+)\}")


def _pom_tag(blok: str, naam: str) -> str | None:
    match = re.search(rf"<{naam}>\s*([^<]*?)\s*</{naam}>", blok)
    return match.group(1) if match else None


def parse_pom(tekst: str) -> list[Pakket]:
    """pom.xml dependencies. ${property} references are resolved from the same file; versions that stay
    unresolved (from a parent or BOM) or that are ranges only mark the dependency as direct."""
    tekst = re.sub(r"<!--.*?-->", "", tekst, flags=re.S)
    waarden: dict[str, str] = {}
    for blok in re.findall(r"<properties>(.*?)</properties>", tekst, re.S):
        for naam, waarde in re.findall(r"<([A-Za-z0-9_.-]+)>\s*([^<]*?)\s*</\1>", blok):
            waarden[naam] = waarde
    eigen = POM_BLOKKEN.sub("", tekst)
    parent = re.search(r"<parent>(.*?)</parent>", tekst, re.S)
    for veld in ("version", "groupId"):
        ouder = _pom_tag(parent.group(1), veld) if parent else None
        waarde = _pom_tag(eigen, veld) or ouder
        if waarde:
            waarden[f"project.{veld}"] = waarde
        if ouder:
            waarden[f"project.parent.{veld}"] = ouder

    def los_op(waarde: str | None) -> str | None:
        for _ in range(5):
            if not waarde or "${" not in waarde:
                return waarde
            waarde = POM_VARIABELE.sub(lambda m: waarden.get(m.group(1), m.group(0)), waarde)
        return None if waarde and "${" in waarde else waarde

    uit: list[Pakket] = []
    for blok in re.findall(r"<dependency>(.*?)</dependency>", tekst, re.S):
        groep, artefact = los_op(_pom_tag(blok, "groupId")), los_op(_pom_tag(blok, "artifactId"))
        if not groep or not artefact or "${" in groep + artefact:
            continue
        versie = los_op(_pom_tag(blok, "version"))
        bruikbaar = versie and "${" not in versie and not versie.startswith(("[", "("))
        uit.append((f"{groep}:{artefact}", versie if bruikbaar else None, True))
    return uit


def parse_composer_lock(tekst: str) -> list[Pakket]:
    data = _dict(json.loads(tekst))
    uit: list[Pakket] = []
    for sectie in ("packages", "packages-dev"):
        for pakket in _lijst(data.get(sectie)):
            naam, versie = _dict(pakket).get("name"), _dict(pakket).get("version")
            if isinstance(naam, str) and isinstance(versie, str) and re.match(r"^v?\d", versie):
                uit.append((naam, versie, False))
    return uit


def parse_composer_json(tekst: str) -> list[Pakket]:
    data = _dict(json.loads(tekst))
    return [(naam, None, True) for sectie in ("require", "require-dev") for naam in _dict(data.get(sectie))
            if "/" in naam]  # skips php, ext-* and lib-* platform requirements


def parse_gemfile_lock(tekst: str) -> list[Pakket]:
    """Gemfile.lock: the specs of GEM sections; the DEPENDENCIES section holds the direct gems."""
    gems: list[tuple[str, str]] = []
    direct: set[str] = set()
    sectie, in_specs = "", False
    for regel in tekst.splitlines():
        if regel and not regel.startswith(" "):
            sectie, in_specs = regel.strip(), False
            continue
        if sectie == "GEM":
            if regel.strip() == "specs:":
                in_specs = True
                continue
            match = re.match(r"^ {4}([A-Za-z0-9_.-]+) \(([^)]+)\)$", regel)
            if in_specs and match:
                gems.append((match.group(1), match.group(2).split("-", 1)[0]))  # drop a platform suffix
        elif sectie == "DEPENDENCIES":
            match = re.match(r"^ {2}([A-Za-z0-9_.-]+)", regel)
            if match:
                direct.add(match.group(1).lower())
    return [(naam, versie, naam.lower() in direct) for naam, versie in gems]


def parse_cargo_lock(tekst: str) -> list[Pakket]:
    """Cargo.lock: crates.io packages; dependencies of the workspace's own packages (no source) are direct."""
    pakketten = [p for p in _lijst(tomllib.loads(tekst).get("package")) if isinstance(p, dict)]
    direct = {str(dep).split(" ")[0] for p in pakketten if not p.get("source")
              for dep in _lijst(p.get("dependencies"))}
    uit: list[Pakket] = []
    for pakket in pakketten:
        naam, versie, bron = pakket.get("name"), pakket.get("version"), str(pakket.get("source") or "")
        if isinstance(naam, str) and isinstance(versie, str) and "crates.io" in bron:
            uit.append((naam, versie, naam in direct))
    return uit


# ---------------------------------------------------------------- file recognition

BESTANDEN = {
    "packages.config": ("nuget", parse_nuget_project),
    "directory.packages.props": ("nuget", parse_nuget_project),
    "directory.build.props": ("nuget", parse_nuget_project),
    "packages.lock.json": ("nuget", parse_nuget_lock),
    "package-lock.json": ("npm", parse_npm_lock),
    "npm-shrinkwrap.json": ("npm", parse_npm_lock),
    "yarn.lock": ("npm", parse_yarn_lock),
    "pnpm-lock.yaml": ("npm", parse_pnpm_lock),
    "package.json": ("npm", parse_package_json),
    "uv.lock": ("pypi", parse_uv_lock),
    "poetry.lock": ("pypi", parse_poetry_lock),
    "pipfile.lock": ("pypi", parse_pipfile_lock),
    "pipfile": ("pypi", parse_pipfile),
    "pyproject.toml": ("pypi", parse_pyproject),
    "go.mod": ("go", parse_go_mod),
    "pom.xml": ("maven", parse_pom),
    "composer.lock": ("composer", parse_composer_lock),
    "composer.json": ("composer", parse_composer_json),
    "gemfile.lock": ("rubygems", parse_gemfile_lock),
    "cargo.lock": ("cargo", parse_cargo_lock),
}
# Installed or vendored dependencies are never scanned as the repository's own files.
ALTIJD_OVERSLAAN = ("/node_modules/", "/vendor/", "/.venv/", "/site-packages/", "/bower_components/")


def herken(pad: str):
    """(ecosystem, parser) for a dependency file, or None."""
    naam = pad.rsplit("/", 1)[-1].lower()
    if naam.endswith((".csproj", ".fsproj", ".vbproj")):
        return "nuget", parse_nuget_project
    if naam in BESTANDEN:
        return BESTANDEN[naam]
    if naam.endswith(".txt") and ("requirements" in naam or "/requirements/" in "/" + pad.lower()):
        return "pypi", parse_requirements
    return None
