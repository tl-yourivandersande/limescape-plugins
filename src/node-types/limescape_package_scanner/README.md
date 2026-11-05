# Azure DevOps package scanner

Scans release branches in two Azure DevOps Git repositories for NuGet package references and queries OSV.dev for NuGet advisories. The node only performs read-only requests.

## Credentials and platform prerequisite

The manifest expects two platform credential types: `limescapeAzureDevOpsPatApi` with secret value `pat`, or `limescapeAzureDevOpsOAuth2Api` with bearer value `accessToken`. The selected credential must be resolvable through SDK 0.2.2 using `team`, `personal`, or `personal_type` selection. These names and fields are an integration contract proposed for platform provisioning; the plugin cannot create credential types or implement OAuth consent/refresh. Confirm the types and token lifecycle with a Limescape administrator before activation. Never put a real token in plugin configuration, code, tests, or this repository.

A PAT should have only Azure DevOps Code (Read) permission for the target project. OAuth must carry an equivalent delegated read scope. OSV queries are anonymous.

## Parameters

Configure the Azure DevOps organization, project, Web/Core repository names, authentication method, credential selection, and minimum major version. `release_lines` is optional comma-separated input; blank scans all qualifying lines. `onderdelen` is `alles`, `componenten`, or `kwetsbaarheden`; `markdown` adds a compact advisory report. The node emits a `result` object with release branches, package records, vulnerability matches, and scan metadata.

The scanner uses Azure DevOps REST API 7.1, NuGet project file formats (`.csproj`, `packages.config`, `Directory.Packages.props`) and OSV.dev. Results are bounded to 2,500 file entries per repository request. It excludes test/sandbox/tool paths and does not write to Azure DevOps.

## Tests

CI runs manifest validation, import checks and the repository's test suite. Tests use synthetic inputs and fake HTTP/credential providers only; run a separate smoke test in a non-production flow after the credential contract is deployed.
