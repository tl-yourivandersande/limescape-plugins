# Package scanner

Scans the release branches of one or more Azure DevOps or GitHub repositories for dependencies, looks up the newest stable versions of the direct dependencies and matches every dependency in use, transitive ones included, against OSV.dev advisories. The node only performs read-only requests.

Supported package types: NuGet (.NET), npm, PyPI (Python), Go, Maven (Java), Composer (PHP), RubyGems (Ruby) and Cargo (Rust).

## Credentials and platform prerequisite

The `credential_code` field is a dropdown of the team's credentials, like the credential fields of the built-in nodes. It lists:

| Choice | Credential | Resolved as |
|--|--|--|
| `[Team] <name>` | a team credential: a personal access token of the generic `genericSecret` type ("Secret", value field `secret`), or the platform's GitHub type `githubOAuth2Api` (GitHub App user token) | `mode="team"` |
| `[Persoonlijk] <name>` | the editor's own GitHub credential; everyone who runs the flow uses it | `mode="personal"` |
| `[Aanroeper] GitHub` | stored as `@user:githubOAuth2Api`: the GitHub credential of whoever starts the flow | `mode="personal_type"` |

The node finds the type itself. For a code it tries a team credential first and then a fixed personal one, and per mode a Secret first and then, on GitHub, the GitHub type. The platform checks the type before it decrypts anything, so a wrong guess reveals nothing. Azure DevOps only accepts a Secret. A Secret is team-only, so it has no `[Aanroeper]` choice. A team administrator must first link `genericSecret` to the team (credential type links) before a credential of it can be created.

A personal access token is sent as Basic auth (empty user name) to Azure DevOps and as a Bearer token to GitHub. A GitHub credential is resolved with `oauth2=True`: the platform refreshes the expiring GitHub App user token, stores the rotated refresh token and hands the node only `accessToken` and the credential's plain fields, never the refresh token or client secret. This needs a platform version whose plugin credential capability supports every OAuth2 type. On an older platform the node stops with "Dit platform ondersteunt GitHub OAuth voor plugins nog niet". The GitHub App's client id and secret are configured on the platform, never in this repository. The token sees the repositories the app is installed on and the user has access to, with the app's permissions, so the app needs Contents (Read).

`[Aanroeper]` only works in runs for which the platform knows the user: a chat, the node editor, the Teams bot, or a scheduled run that carries its owner. A run without a known user stops with "geen gebruiker bekend". Use a team credential there. A deep agent leaves out a flow tool whose node uses `@user:githubOAuth2Api` when the user has no GitHub credential.

The dropdown replaces a text field (releases up to 0.1.4). Existing nodes keep their stored code, which the dropdown shows as the same credential. `limescape-plugin compat` reports the change of field type.

Azure DevOps OAuth is not supported: the `microsoftAzureDevOpsMcpOAuth2Api` type issues tokens for the Azure DevOps MCP server, not for the REST API this node calls. Never put a real token in plugin configuration, code, tests, or this repository.

Platform refusals of a credential (unknown or inactive credential, wrong type, missing GitHub link, authorization needed again) become a specific safe error; the platform's own message is not passed on.

Use the least privilege: an Azure DevOps PAT with only Code (Read) for the target project, a GitHub fine-grained token with only Contents (Read) on the target repositories, or a GitHub App with only Contents (Read). The credential is only sent to `dev.azure.com` or `api.github.com`; deps.dev, packagist.org and OSV.dev requests are anonymous.

## Parameters

- `provider`: `azure_devops` (default) or `github`.
- `credential_code`: the credential from the dropdown: a credential code, or `@user:githubOAuth2Api` for the GitHub credential of whoever starts the flow; see above.
- `organization`: the Azure DevOps organization or the GitHub owner (user or organization).
- `project`: the Azure DevOps project; not used for GitHub.
- `repositories`: a comma-separated list of up to 10 repositories. On GitHub an entry may be `owner/name` to override the owner. Each entry is used as its label in the report.
- `ecosystems`: the package types to scan (`nuget`, `npm`, `pypi`, `go`, `maven`, `composer`, `rubygems`, `cargo`; aliases such as `python`, `.net` and `javascript` are accepted). Blank scans all types. Files of other types are not read.
- `include_default_branch` (default on): also scan the repository's default branch (for example `main`) as its own line, unless it is `develop` or a release/hotfix branch.
- `min_major` / `max_major`: the major-version range of release/hotfix branches; blank `max_major` means no upper limit. Set `max_major` when a repository also has year-numbered branches (for example `release/2019.1`) that should not count.
- `release_lines` (input alias `release_lijnen`): optional list or comma-separated text such as `main, develop, 9.2`; a full version is reduced to its line. Blank scans all lines.
- `exclude_paths`: comma-separated, case-insensitive path fragments; matching files are skipped. The default skips test, sandbox and load-test projects. A path is matched with a leading `/`, so `/tools/` also matches a root folder. `node_modules`, `vendor`, `.venv`, `site-packages` and `bower_components` are always skipped.
- `exclude_packages`: package names that are left out of the packages, newest versions and advisories.
- `latest_packages`: package names to look up in the public registry; a name may carry a type prefix such as `pypi:requests` or `maven:org.slf4j:slf4j-api`. Blank looks up every direct dependency (at most 300).
- `onderdelen`: `alles` (packages, newest versions and vulnerabilities), `componenten` (packages and newest versions) or `kwetsbaarheden` (vulnerabilities only).
- `markdown`: adds a package table per release line and a vulnerability report.

## Dependency files

| Type | Files | Direct dependencies |
|--|--|--|
| NuGet | `*.csproj`, `*.fsproj`, `*.vbproj`, `packages.config`, `Directory.Packages.props`, `Directory.Build.props`, `packages.lock.json` | project references; lockfile `Direct` entries |
| npm | `package-lock.json`, `npm-shrinkwrap.json`, `yarn.lock` (classic and Berry), `pnpm-lock.yaml`, `package.json` | lockfile v2/v3 root entries, otherwise `package.json` |
| PyPI | `uv.lock`, `poetry.lock`, `Pipfile.lock`, `requirements*.txt` (`==` pins), `pyproject.toml`, `Pipfile` | `uv.lock` project entries, `pyproject.toml`/`Pipfile`, pip-compile `# via -r` |
| Go | `go.mod` | requirements without `// indirect` |
| Maven | `pom.xml` (`${property}` from the same file) | all declared dependencies |
| Composer | `composer.lock`, `composer.json` | `composer.json` |
| RubyGems | `Gemfile.lock` | the `DEPENDENCIES` section |
| Cargo | `Cargo.lock` | dependencies of the workspace's own packages |

Only exact versions are checked: version ranges, MSBuild variables, wildcards, Maven versions from a parent or BOM, local paths and workspace links are skipped. A manifest without an exact version only marks the dependency as direct for the lockfiles of the same branch. Gradle build files are not read.

## Output

The `result` object contains `gecontroleerd_op`, `onderdelen`, `bron`, `ecosystemen`, `uitgesloten_packages`, `uitgesloten_paden`, `nieuwste_versies` (per package type and package: `nieuwste`, `datum` and `status`: `ok`, `niet gevonden op <registry>` or `register niet bereikbaar`), `releases`, `statistiek` (per repository: branches, dependency files, files read, unique dependencies and direct dependencies, plus the duration) and `waarschuwingen`.

Each release has `release_lijn`, `versie` (the newest version over all repositories), `branches` per repository, `packages` (direct dependencies per package type, then package name to version(s) per repository), `aantal_kwetsbare_packages`, `hoogste_severity` and `kwetsbaarheden` (package type, package, repository, version, direct, severity, advisory, CVE, fixed-in versions and summary). Advisories that OSV.dev returns several times under aliases (for example a `PYSEC-`, `GO-` or `RUSTSEC-` record next to its `GHSA-` record) are reported once, preferring the record that carries a severity.

## Behaviour and limits

Branches are found with the git-flow prefixes `develop`, `release/<version>` and `hotfix/<version>`; per release line and repository the newest version is scanned (a release candidate counts before its final version). The default branch is listed first, then develop, then the release lines from newest to oldest. Files are read through Azure DevOps REST API 7.1 (refs with continuation, commit, recursive tree, blobs) or the GitHub REST API (matching refs, recursive tree, blobs), and identical files are read and parsed once. Newest versions come from deps.dev (NuGet, npm, PyPI, Go, Maven, RubyGems, Cargo) and packagist.org (Composer).

Requests are bounded: 20 ref pages per prefix, 50 release lines and 3,000 dependency files per repository, files up to 20 MB, 16 parallel source requests, 8 parallel public requests, 300 newest-version lookups, 20,000 dependencies for OSV.dev and 1,000 advisory details. A bound that is hit, a truncated GitHub tree, an unreadable or malformed file, an unreachable registry or a missing advisory detail becomes a warning. Access denied (including Azure DevOps' 203 sign-in page), an invalid GitHub token and an exhausted GitHub rate limit stop the scan with a safe error.

## Tests

CI runs manifest validation, import checks and the repository's test suite. Tests use synthetic inputs and a fake HTTP/credential backend only: `tests/test_node.py` runs full scans against fake Azure DevOps and GitHub backends, `tests/test_ecosystemen.py` covers each dependency-file parser. Run a separate smoke test against a real repository, for example locally with the SDK `FakeContext` and a real HTTP handler, or in a non-production flow after the credential contract is deployed.
