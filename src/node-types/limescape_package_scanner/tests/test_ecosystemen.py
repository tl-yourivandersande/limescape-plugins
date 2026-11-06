"""Unit tests for the dependency-file parsers, loaded the way the platform loads the node type."""

import importlib
import json
from pathlib import Path

from limescape_plugin_sdk.loader import load_node_module

NODE = Path(__file__).resolve().parents[1]
load_node_module(NODE, "limescape_package_scanner")
eco = importlib.import_module("limescape_plugins.limescape_package_scanner._ecosystemen")


def test_file_recognition_and_package_type_aliases():
    assert eco.herken("src/App/App.csproj")[0] == "nuget"
    assert eco.herken("Directory.Packages.props")[0] == "nuget"
    assert eco.herken("web/package-lock.json")[0] == "npm"
    assert eco.herken("web/pnpm-lock.yaml")[0] == "npm"
    assert eco.herken("requirements-dev.txt")[0] == "pypi"
    assert eco.herken("requirements/base.txt")[0] == "pypi"
    assert eco.herken("Gemfile.lock")[0] == "rubygems"
    assert eco.herken("README.md") is None and eco.herken("notes.txt") is None
    assert [eco.ecosysteem_code(x) for x in ("Python", ".NET", "javascript", "rust", "cobol")] == [
        "pypi", "nuget", "npm", "cargo", None]


def test_nuget_project_and_lock():
    project = '<PackageReference Include="A" Version="1.0.0" />\n<PackageReference Include="B">\n' \
              '  <Version>2.0.0</Version>\n</PackageReference>\n<PackageReference Include="C" Version="$(V)" />'
    assert eco.parse_nuget_project(project) == [("A", "1.0.0", True), ("B", "2.0.0", True)]
    lock = {"version": 1, "dependencies": {"net8.0": {
        "A": {"type": "Direct", "requested": "[1.0.0, )", "resolved": "1.0.0"},
        "T": {"type": "Transitive", "resolved": "3.1.0"},
        "MyLib": {"type": "Project"},
    }}}
    assert eco.parse_nuget_lock(json.dumps(lock)) == [("A", "1.0.0", True), ("T", "3.1.0", False)]


def test_npm_lockfile_v3_marks_direct_dependencies():
    lock = {"lockfileVersion": 3, "packages": {
        "": {"dependencies": {"lodash": "^4"}, "devDependencies": {"jest": "^29"}},
        "packages/app": {"dependencies": {"react": "^18"}},
        "node_modules/lodash": {"version": "4.17.21"},
        "node_modules/jest": {"version": "29.7.0", "dev": True},
        "node_modules/react": {"version": "18.2.0"},
        "node_modules/minimist": {"version": "1.2.8"},
        "node_modules/foo/node_modules/lodash": {"version": "3.10.1"},
        "node_modules/app": {"resolved": "packages/app", "link": True},
        "node_modules/str": {"name": "string-width", "version": "4.2.3"},
    }}
    assert sorted(eco.parse_npm_lock(json.dumps(lock))) == [
        ("jest", "29.7.0", True), ("lodash", "3.10.1", False), ("lodash", "4.17.21", True),
        ("minimist", "1.2.8", False), ("react", "18.2.0", True), ("string-width", "4.2.3", False)]


def test_npm_lockfile_v1_and_package_json():
    lock = {"lockfileVersion": 1, "dependencies": {
        "a": {"version": "1.0.0", "dependencies": {"b": {"version": "2.0.0"}}},
        "c": {"version": "github:user/c#abc"},
    }}
    assert sorted(eco.parse_npm_lock(json.dumps(lock))) == [("a", "1.0.0", False), ("b", "2.0.0", False)]
    manifest = {"dependencies": {"a": "^1.0.0", "pinned": "2.3.4"}, "devDependencies": {"jest": "29.7.0-beta.1"}}
    assert eco.parse_package_json(json.dumps(manifest)) == [
        ("a", None, True), ("pinned", "2.3.4", True), ("jest", "29.7.0-beta.1", True)]


def test_yarn_lock_classic_and_berry():
    classic = '# yarn lockfile v1\n\n"@babel/core@^7.0.0", "@babel/core@^7.1.0":\n  version "7.2.0"\n' \
              '  dependencies:\n    debug "^4"\n\nlodash@^4.17.0:\n  version "4.17.21"\n'
    assert eco.parse_yarn_lock(classic) == [("@babel/core", "7.2.0", False), ("lodash", "4.17.21", False)]
    berry = '__metadata:\n  version: 6\n\n"lodash@npm:^4.17.21":\n  version: 4.17.21\n  resolution: "x"\n\n' \
            '"app@workspace:.":\n  version: 0.0.0-use.local\n'
    assert eco.parse_yarn_lock(berry) == [("lodash", "4.17.21", False)]


def test_pnpm_lock_versions_5_6_and_9():
    v5 = "lockfileVersion: 5.4\npackages:\n  /lodash/4.17.21:\n    resolution: {}\n" \
         "  /@babel/core/7.2.0_supports-color@8.1.1:\n    dev: true\n"
    v6 = "lockfileVersion: '6.0'\npackages:\n  /@babel/core@7.2.0(supports-color@8.1.1):\n    resolution: {}\n"
    v9 = "lockfileVersion: '9.0'\nimporters:\n  .:\n    dependencies:\n      lodash:\n        version: 4.17.21\n" \
         "packages:\n  '@babel/core@7.2.0':\n    resolution: {}\n  lodash@4.17.21:\n    resolution: {}\n" \
         "snapshots:\n  lodash@4.17.21: {}\n"
    assert eco.parse_pnpm_lock(v5) == [("lodash", "4.17.21", False), ("@babel/core", "7.2.0", False)]
    assert eco.parse_pnpm_lock(v6) == [("@babel/core", "7.2.0", False)]
    assert eco.parse_pnpm_lock(v9) == [("@babel/core", "7.2.0", False), ("lodash", "4.17.21", False)]


def test_python_lockfiles():
    uv_lock = '''version = 1
[[package]]
name = "my-app"
version = "0.1.0"
source = { editable = "." }
dependencies = [{ name = "requests" }]
[package.dev-dependencies]
dev = [{ name = "pytest" }]

[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "pytest"
version = "8.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "urllib3"
version = "2.0.7"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "local-lib"
version = "0.0.1"
source = { path = "../local-lib" }
'''
    assert eco.parse_uv_lock(uv_lock) == [("requests", "2.31.0", True), ("pytest", "8.0.0", True),
                                          ("urllib3", "2.0.7", False)]
    poetry = '[[package]]\nname = "Django"\nversion = "4.2.0"\n\n[[package]]\nname = "mylib"\nversion = "1.0"\n' \
             '[package.source]\ntype = "directory"\nurl = "../mylib"\n'
    assert eco.parse_poetry_lock(poetry) == [("Django", "4.2.0", False)]
    pipfile_lock = {"default": {"requests": {"version": "==2.31.0"}}, "develop": {"pytest": {"version": "==8.0.0"},
                                                                                  "local": {"path": "."}}}
    assert eco.parse_pipfile_lock(json.dumps(pipfile_lock)) == [("requests", "2.31.0", False),
                                                                 ("pytest", "8.0.0", False)]
    assert eco.parse_pipfile('[packages]\nrequests = "*"\n[dev-packages]\npytest = "==8.0"\n') == [
        ("requests", None, True), ("pytest", None, True)]


def test_pyproject_and_requirements():
    pyproject = '''[project]
dependencies = ["requests>=2", "Flask[async]==3.0.0; python_version>'3.8'"]
[project.optional-dependencies]
socks = ["PySocks"]
[dependency-groups]
dev = ["pytest", {include-group = "lint"}]
[tool.poetry.dependencies]
python = "^3.12"
django = "^4.2"
'''
    assert eco.parse_pyproject(pyproject) == [
        ("requests", None, True), ("Flask", "3.0.0", True), ("PySocks", None, True), ("pytest", None, True),
        ("django", None, True)]
    pip_compile = """# This file is autogenerated by pip-compile
requests==2.31.0 \\
    --hash=sha256:abc
    # via -r requirements.in
urllib3==2.0.7
    # via requests
idna==3.4
    # via
    #   requests
    #   -r requirements.in
-e ./local
git+https://github.com/x/y.git
"""
    assert eco.parse_requirements(pip_compile) == [("requests", "2.31.0", True), ("urllib3", "2.0.7", False),
                                                   ("idna", "3.4", True)]
    hand_written = "# web\nDjango==4.2.0\npytest>=8\n"
    assert eco.parse_requirements(hand_written) == [("Django", "4.2.0", True), ("pytest", None, True)]


def test_go_mod():
    go_mod = "module example.com/x\n\ngo 1.22\n\nrequire github.com/a/b v1.0.0\n\nrequire (\n" \
             "\tgithub.com/gin-gonic/gin v1.9.1\n\tgolang.org/x/sys v0.15.0 // indirect\n\t// a comment\n)\n" \
             "replace github.com/a/b => ../b\n"
    assert eco.parse_go_mod(go_mod) == [("github.com/a/b", "v1.0.0", True),
                                        ("github.com/gin-gonic/gin", "v1.9.1", True),
                                        ("golang.org/x/sys", "v0.15.0", False)]


def test_maven_pom_resolves_properties():
    pom = """<project>
  <parent><groupId>org.springframework.boot</groupId><artifactId>parent</artifactId><version>3.2.0</version></parent>
  <groupId>com.example</groupId>
  <artifactId>app</artifactId>
  <version>1.4.0</version>
  <!-- <dependency><groupId>x</groupId><artifactId>commented</artifactId><version>1</version></dependency> -->
  <properties><log4j.version>2.14.1</log4j.version></properties>
  <dependencies>
    <dependency><groupId>org.apache.logging.log4j</groupId><artifactId>log4j-core</artifactId>
      <version>${log4j.version}</version></dependency>
    <dependency><groupId>${project.groupId}</groupId><artifactId>shared</artifactId>
      <version>${project.version}</version></dependency>
    <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-web</artifactId></dependency>
    <dependency><groupId>a</groupId><artifactId>ranged</artifactId><version>[1.0,2.0)</version></dependency>
    <dependency><groupId>b</groupId><artifactId>unknown</artifactId><version>${missing}</version></dependency>
  </dependencies>
</project>"""
    assert eco.parse_pom(pom) == [
        ("org.apache.logging.log4j:log4j-core", "2.14.1", True), ("com.example:shared", "1.4.0", True),
        ("org.springframework.boot:spring-boot-starter-web", None, True), ("a:ranged", None, True),
        ("b:unknown", None, True)]


def test_composer_gemfile_and_cargo():
    composer_lock = {"packages": [{"name": "symfony/console", "version": "v6.4.1"},
                                  {"name": "acme/dev", "version": "dev-main"}],
                     "packages-dev": [{"name": "phpunit/phpunit", "version": "10.5.0"}]}
    assert eco.parse_composer_lock(json.dumps(composer_lock)) == [("symfony/console", "v6.4.1", False),
                                                                  ("phpunit/phpunit", "10.5.0", False)]
    composer_json = {"require": {"php": ">=8.1", "ext-json": "*", "symfony/console": "^6.4"}}
    assert eco.parse_composer_json(json.dumps(composer_json)) == [("symfony/console", None, True)]
    gemfile_lock = """GIT
  remote: https://github.com/x/y.git
  specs:
    y (0.1.0)

GEM
  remote: https://rubygems.org/
  specs:
    nokogiri (1.15.4-x86_64-linux)
      racc (~> 1.4)
    racc (1.7.1)
    rails (7.1.2)

PLATFORMS
  x86_64-linux

DEPENDENCIES
  nokogiri
  rails (~> 7.1)
"""
    assert eco.parse_gemfile_lock(gemfile_lock) == [("nokogiri", "1.15.4", True), ("racc", "1.7.1", False),
                                                    ("rails", "7.1.2", True)]
    cargo_lock = '''version = 3
[[package]]
name = "my-app"
version = "0.1.0"
dependencies = ["serde", "time 0.1.43"]

[[package]]
name = "serde"
version = "1.0.190"
source = "registry+https://github.com/rust-lang/crates.io-index"

[[package]]
name = "time"
version = "0.1.43"
source = "sparse+https://index.crates.io/"

[[package]]
name = "libc"
version = "0.2.150"
source = "registry+https://github.com/rust-lang/crates.io-index"

[[package]]
name = "private"
version = "1.0.0"
source = "registry+https://my-registry.example/index"
'''
    assert eco.parse_cargo_lock(cargo_lock) == [("serde", "1.0.190", True), ("time", "0.1.43", True),
                                                ("libc", "0.2.150", False)]


def test_name_keys():
    assert eco.canoniek("pypi", "Zope.Interface") == "zope-interface"
    assert eco.canoniek("npm", "Lodash") == "Lodash"
    assert eco.sleutel("nuget", "Newtonsoft.Json") == "newtonsoft.json"
