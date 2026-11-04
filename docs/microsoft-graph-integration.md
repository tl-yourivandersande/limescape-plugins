# Microsoft Graph: SharePoint and To Do

**Status:** initial plugin implementation on this branch, using the user-provided assumption that Studio resolves Microsoft OAuth credentials and refreshes tokens, returning a current Microsoft Graph access token at run time. Each node has explicit credential type/token-field placeholders. This is not ready for activation until those names are mapped and verified against Studio.

## Implemented nodes and current scope

| Node | Current operations | Known first-version limits |
|---|---|---|
| `team17_sharepoint` | Sites: search, get by URL, list lists, list document libraries. Lists: list/get/create/update/delete items. Libraries: list files (root or folder), search, get metadata, download/upload UTF-8 text (1 MB cap), create folder, delete file or folder | Bounded paging (max 1000 results, 10 pages); no binary transfer, upsert, ETag handling or conditional writes |
| `team17_microsoft_todo` | List task lists, list/get/create/update tasks | No delete or paging |

Inputs use site/list/drive/task IDs (the SharePoint node can look them up from a site URL) and JSON object fields; results are returned under the node output key. Writes do not retry automatically. Node codes and manifests still need reserved-code/catalog validation in CI.

## Authentication contract (assumed Studio responsibility)

Assume Studio's configured Microsoft OAuth credential resolves at run time to a **currently valid access token for Microsoft Graph**, with consent, refresh-token rotation, secure persistence and revocation handled by Studio/platform. Nodes resolve a selected credential and send its access token as a Bearer token to the fixed Graph v1.0 host. They do not implement OAuth consent or refresh and must never receive/store refresh tokens or client secrets.

Each node defines `CREDENTIAL_TYPE` and `TOKEN_FIELD` as `REPLACE_WITH_STUDIO_...` constants. Replace them with the exact Studio credential type and token property before use. Credential reference/mode and token must never be exposed in outputs/logs/traces. A development Studio smoke test must confirm that successive runs receive valid tokens and that revoked credentials fail safely. If the assumed Studio contract is unavailable, pause rather than adding OAuth logic to the plugin without authorization.

Nodes currently expose selected team and selected personal credential-code modes. Personal credentials are explicitly shared through the flow when selected; use only where authorized. No caller-specific credential-type mode is included until its exact Studio resolver/identity behavior is confirmed.

## Microsoft Entra permissions

The initial design uses delegated access. Studio/tenant administrators configure consent and permissions. Candidate scopes to verify against current Microsoft Graph endpoint documentation:

- Lists and site lookup read: `Sites.Read.All`; create/update/delete: `Sites.ReadWrite.All`, subject to narrower endpoint options.
- Libraries: `Files.Read` / `Files.ReadWrite` for the signed-in user's files, or appropriate `Sites.*` permission for site drives.
- To Do: delegated `Tasks.Read` / `Tasks.ReadWrite`; no app-only fallback.

The exact endpoint permission matrix and least-privilege option must be verified before release. Do not assume `Sites.Selected` supports every delegated Lists operation.

## Node behavior and safety

### SharePoint

One node covers sites, Lists and document libraries; the form only shows the fields the selected action uses (`depends_on.visible_when`). Requests use validated site, list, drive and item path segments and fixed `graph.microsoft.com/v1.0` endpoints. List actions follow `@odata.nextLink` only back to the Graph host, up to the configured maximum.

Lists: create/update requires a non-empty JSON object. Upsert is omitted because it is not an atomic Graph primitive. Update uses PATCH on `/fields`; ETag/If-Match conflict controls are not implemented yet.

Document libraries: only UTF-8 text, capped at 1 MB for upload and download. Upload uses a path and the PUT content endpoint and replaces an existing file at that path. Folder creation fails on a name conflict. Binary file transfer and ETag control need follow-up before broader production use.

Delete actions remove one list item or drive item by ID; SharePoint moves it to the site recycle bin.

### To Do

Endpoints are delegated `/me/todo` endpoints. Create requires a title; update only accepts an explicit allowlist and PATCH leaves omitted properties unchanged. No task deletion is exposed.

### Common security

- `capabilities: [credentials, http]`; fixed Graph origin; bounded request timeouts.
- No arbitrary URLs, custom auth headers or user-controlled hosts.
- Safe Graph errors: HTTP status plus Graph's error code only; no provider response body, message or token in output.
- Never retry writes automatically. Respect caller permissions; do not silently switch credential owner/mode.
- Unit tests use synthetic tokens/data only. They do not prove Studio's token refresh, credential scoping or tenant consent; run a development-tenant smoke test.

## Delivery checklist

1. Map each placeholder to the exact Studio Microsoft credential type/value contract. Verify credential-mode availability and token behavior; no new platform OAuth work is assumed.
2. Confirm Entra tenant/app registration and delegated permissions for target Graph endpoints.
3. Complete manifest/code CI and a Studio smoke test for read and write operations.
4. Review and merge/release/activate the bundle; administrators handle Studio consent/configuration and Limescape activation.
