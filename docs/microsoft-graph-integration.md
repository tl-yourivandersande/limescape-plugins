# Microsoft Graph: SharePoint and To Do

**Status:** initial plugin implementation. Both nodes use the platform's Microsoft 365 (OAuth2) credential type `microsoft365OAuth2Api` with `oauth2=True`, and the platform refreshes the Graph token. This needs a platform version whose plugin credential capability supports every OAuth2 type, and a Studio smoke test before activation.

## Implemented nodes and current scope

| Node | Current operations | Known first-version limits |
|---|---|---|
| `limescape_sharepoint` | Sites: search, get by URL, list lists, list document libraries. Lists: list/get/create/update/delete items. Libraries: list files (root or folder), search, get metadata, download/upload UTF-8 text (1 MB cap), create folder, delete file or folder | Bounded paging (max 1000 results, 10 pages); no binary transfer, upsert, ETag handling or conditional writes |
| `limescape_microsoft_todo` | List task lists, list/get/create/update tasks | No delete or paging |

Inputs use site/list/drive/task IDs (the SharePoint node can look them up from a site URL) and JSON object fields; results are returned under the node output key. Writes do not retry automatically. Node codes and manifests still need reserved-code/catalog validation in CI.

## Authentication contract

Each node defines `CREDENTIAL_TYPE = "microsoft365OAuth2Api"` and `TOKEN_FIELD = "accessToken"` and calls `ctx.credentials.resolve(reference, mode=..., expected_type=CREDENTIAL_TYPE, oauth2=True)`. The platform resolves the credential to a **currently valid access token for Microsoft Graph**: it refreshes the token at the tenant's Microsoft endpoint, stores the rotated refresh token and returns `accessToken` plus the credential's plain fields (such as `tenantId`), never the refresh token or client secret. Nodes send the access token as a Bearer token to the fixed Graph v1.0 host and implement no OAuth consent or refresh themselves.

The `microsoft365OAuth2Api` type uses the customer's own Entra app registration (client id, secret and tenant on the credential). Its default scope covers mail, calendar and contacts, so set the credential's scope to the Graph permissions below. Credential reference/mode and token must never be exposed in outputs/logs/traces. A development Studio smoke test must confirm that successive runs receive valid tokens and that revoked credentials fail safely.

The credential is chosen in a dropdown (`lookup` on `credentials.Credential`, like the built-in nodes) with three kinds of choices. `[Team]` is a team credential (`mode="team"`). `[Persoonlijk]` is the editor's own credential, shared with everyone who runs the flow (`mode="personal"`), so use it only where that is authorized. `[Aanroeper]` is stored as `@user:microsoft365OAuth2Api` and resolves to the credential of whoever starts the flow (`mode="personal_type"`). The platform establishes that person from the trusted run context, never from flow input. For a code the node tries `team` first and then `personal`. The older `credential_mode` field is deprecated, kept for compatibility and no longer shown.

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

1. Deploy a platform version whose plugin credential capability refreshes every OAuth2 type (`microsoft365OAuth2Api` included). Verify credential-mode availability and token behavior.
2. Confirm Entra tenant/app registration and delegated permissions for target Graph endpoints.
3. Complete manifest/code CI and a Studio smoke test for read and write operations.
4. Review and merge/release/activate the bundle; administrators handle Studio consent/configuration and Limescape activation.
