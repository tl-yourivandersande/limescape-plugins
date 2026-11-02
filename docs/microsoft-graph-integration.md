# Microsoft Graph: Lists, document libraries and To Do

**Status:** initial plugin implementation on this branch, using the user-provided assumption that Studio resolves Microsoft OAuth credentials and refreshes tokens, returning a current Microsoft Graph access token at run time. Each node has explicit credential type/token-field placeholders. This is not ready for activation until those names are mapped and verified against Studio.

## Implemented nodes and current scope

| Node | Current operations | Known first-version limits |
|---|---|---|
| `team17_sharepoint_list` | List items, get one item, create item, update item fields by item ID | One response page; no delete, upsert, ETag handling or conditional writes |
| `team17_sharepoint_file` | List root children, get metadata, download UTF-8 text, upload UTF-8 text (1 MB cap) | No binary transfer, paging, delete, folder creation or ETag conflict handling |
| `team17_microsoft_todo` | List task lists, list/get/create/update tasks | No delete or paging |

Inputs use site/list/drive/task IDs and JSON object fields; results are returned under the node output key. Writes do not retry automatically. Node codes and manifests still need reserved-code/catalog validation in CI.

## Authentication contract (assumed Studio responsibility)

Assume Studio's configured Microsoft OAuth credential resolves at run time to a **currently valid access token for Microsoft Graph**, with consent, refresh-token rotation, secure persistence and revocation handled by Studio/platform. Nodes resolve a selected credential and send its access token as a Bearer token to the fixed Graph v1.0 host. They do not implement OAuth consent or refresh and must never receive/store refresh tokens or client secrets.

Each node defines `CREDENTIAL_TYPE` and `TOKEN_FIELD` as `REPLACE_WITH_STUDIO_...` constants. Replace them with the exact Studio credential type and token property before use. Credential reference/mode and token must never be exposed in outputs/logs/traces. A development Studio smoke test must confirm that successive runs receive valid tokens and that revoked credentials fail safely. If the assumed Studio contract is unavailable, pause rather than adding OAuth logic to the plugin without authorization.

Nodes currently expose selected team and selected personal credential-code modes. Personal credentials are explicitly shared through the flow when selected; use only where authorized. No caller-specific credential-type mode is included until its exact Studio resolver/identity behavior is confirmed.

## Microsoft Entra permissions

The initial design uses delegated access. Studio/tenant administrators configure consent and permissions. Candidate scopes to verify against current Microsoft Graph endpoint documentation:

- Lists read: `Sites.Read.All`; create/update: `Sites.ReadWrite.All`, subject to narrower endpoint options.
- Libraries: `Files.Read` / `Files.ReadWrite` for the signed-in user's files, or appropriate `Sites.*` permission for site drives.
- To Do: delegated `Tasks.Read` / `Tasks.ReadWrite`; no app-only fallback.

The exact endpoint permission matrix and least-privilege option must be verified before release. Do not assume `Sites.Selected` supports every delegated Lists operation.

## Node behavior and safety

### Lists

Requests use validated site, list and item path segments and fixed `graph.microsoft.com/v1.0` endpoints. Create/update requires a non-empty JSON object. Upsert is omitted because it is not an atomic Graph primitive. Update uses PATCH on `/fields`; ETag/If-Match conflict controls are not implemented yet.

### Document libraries

The initial implementation only handles UTF-8 text. Upload uses a drive root path and PUT content endpoint, with a 1 MB input cap. Binary file transfer, overwrite conflict policy, pagination and ETag control need follow-up before broader production use.

### To Do

Endpoints are delegated `/me/todo` endpoints. Create requires a title; update only accepts an explicit allowlist and PATCH leaves omitted properties unchanged. No task deletion is exposed.

### Common security

- `capabilities: [credentials, http]`; fixed Graph origin; bounded request timeouts.
- No arbitrary URLs, custom auth headers or user-controlled hosts.
- Safe status-only Graph errors; no provider response body or token in output.
- Never retry writes automatically. Respect caller permissions; do not silently switch credential owner/mode.
- Unit tests use synthetic tokens/data only. They do not prove Studio's token refresh, credential scoping or tenant consent; run a development-tenant smoke test.

## Delivery checklist

1. Map each placeholder to the exact Studio Microsoft credential type/value contract. Verify credential-mode availability and token behavior; no new platform OAuth work is assumed.
2. Confirm Entra tenant/app registration and delegated permissions for target Graph endpoints.
3. Complete manifest/code CI and a Studio smoke test for read and write operations.
4. Review and merge/release/activate the bundle; administrators handle Studio consent/configuration and Limescape activation.
