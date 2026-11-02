# Microsoft Graph: Lists, document libraries and To Do

**Status:** design proposal; not an implementation or a claim that Microsoft OAuth currently works in Limescape.

## Goal and boundary

Provide three focused flow nodes, backed by Microsoft Graph and one shared authentication layer:

| Node code (proposed) | Resource | Initial operations |
|---|---|---|
| `team17_sharepoint_list` | SharePoint Lists | List items with pagination; get item; create item; update item by ID; optional upsert by configured key only if uniqueness and race behavior are documented |
| `team17_sharepoint_file` | SharePoint document libraries (Graph drives) | List/search files, get metadata, download file content as a documented text/base64 output, upload/create, update/replace content, optionally create folder. No delete in v1. |
| `team17_microsoft_todo` | Microsoft To Do | List task lists and tasks; get task; create task; update task. No delete in v1. |

Names are proposals, subject to checking reserved SDK node codes and the installed catalog before implementation. Inputs must be flow-friendly JSON; outputs must be stable JSON and avoid returning opaque Graph response fields by default. Keep each node stateless.

## Authentication: blocking platform prerequisite

Use delegated Microsoft Entra ID OAuth 2.0 authorization-code flow with PKCE for interactive consent, plus a server-side confidential client for refresh-token exchange. Never put client secrets, access tokens or refresh tokens in node fields, flow state, traces, outputs or public code. Do not ask users to paste bearer tokens. The Graph nodes should request a fresh access token via a platform capability for each run; refresh and secure persistence/rotation stay platform-owned.

The plugin reference docs available during this design state that SDK `ctx.credentials.resolve(..., oauth2=True)` only implements Google Tag Manager OAuth, and that manifests cannot register credential types. Therefore a Microsoft credential type, consent UI, lifecycle and SDK/platform contract must be implemented and deployed before these plugin nodes can be activated. Do not call the integration production-ready until that work lands and is verified in the target deployment.

### Required platform work

1. **Credential schema and storage:** register a stable global type such as `microsoftGraphOAuth2` using a migration/fixture. Store encrypted client/tenant configuration as appropriate; protect access and refresh tokens as secrets. Define whether the Entra app registration is platform-global, team-owned or user-provided. Never store tenant/client secrets in plugin parameters. Validate issuer/tenant and approved authority hosts.
2. **OAuth consent UX:** add Microsoft authorization-code + PKCE sign-in and callback, state/nonce validation, CSRF protection, redirect allowlisting, consent/re-consent, account identity display, revoke/deactivate and safe error handling. Support both personal and team credential setup only if product/security policy permits.
3. **Token lifecycle:** add provider-generic (or Microsoft-specific) platform resolution to refresh an expired/near-expiry token, safely persist refresh-token rotation transactionally, serialize concurrent refreshes, handle revoked/invalid-grant credentials and keep credentials out of logs. Return only a valid short-lived access token to the isolated plugin execution. Enforce the tenant and resource audience; do not return refresh tokens to the plugin.
4. **SDK contract:** extend `ctx.credentials.resolve` with explicit `expected_type="microsoftGraphOAuth2"` and a provider OAuth lifecycle, without weakening current exact team/user/type scoping. Keep personal code, team code and type selection distinct. Do not overload today's `oauth2=True` behavior until it is provider-aware and compatibility-tested.
5. **Identity propagation and UI:** implement/verify exact credential picker modes and caller identity preservation through Deep Agent tools and nested flow inputs. Personal-type selection must resolve the active caller's own connection, never a model-supplied identity. Team and fixed personal connections must follow explicit sharing/authorization rules. Mask credential labels and avoid leaking identity or scopes in telemetry.
6. **Platform tests and rollout:** test consent/state/PKCE, encryption/redaction, selected credential modes, exact type/team/owner scope, refresh rotation/races/revocation, identity propagation, and HTTP behavior. Publish/install the required SDK and deploy migrations/platform services before registering/activating the plugin bundle.

## Microsoft Entra registration and permissions

Use delegated permissions in the initial release because the same flow may run as different Limescape users, and Microsoft To Do operations are user-context operations. The platform administrator must register an Entra application, configure the callback URI, consent to only the needed Microsoft Graph delegated scopes, and specify supported account types/tenant policy. Exact permissions must be confirmed against current Microsoft Graph endpoint documentation before implementation and deployment; do not claim that `Sites.Selected` works for every delegated Lists endpoint without validating its semantics.

Candidate least-privilege scopes to validate:

- Lists: `Sites.Read.All` for read-only, and `Sites.ReadWrite.All` for create/update, subject to endpoint-specific least-privilege options.
- Libraries: `Files.Read` / `Files.ReadWrite` for the signed-in user's files, or corresponding `Sites.*` permission for site-wide drives; choose by endpoint and resource scope.
- To Do: `Tasks.Read` / `Tasks.ReadWrite` delegated permissions. Never silently switch To Do to app-only access.

Request incremental permissions if the platform supports it; separate read-only and write operations when practical. A deployment needing more tenant-wide access than the user's scope must be explicit and administrator-approved.

## Node contracts

### Lists

- Select site and list by validated ID (or a separately resolved, non-ambiguous display-name lookup); do not accept arbitrary request URLs.
- Create/update accept explicit `fields` objects and optionally item ID. Validate JSON object type, field count/size, and reserved/system fields; do not allow inputs to set URL/host or auth headers.
- Upsert is not a Graph atomic primitive. If offered, query an indexed key, fail on zero/multiple matches according to a selected create/update policy, and document race/idempotency behavior. Prefer separate create and update operations first.
- Handle `@odata.nextLink` with page caps and same-origin validation; project only requested fields. Respect `If-Match`/ETag for safe updates when supplied; map 412 conflicts to safe errors.

### Document libraries

- Require site/drive identifiers and a path/item ID; derive URLs only from fixed `graph.microsoft.com` endpoints and validated, encoded path segments.
- Initial write behavior should support create-new and replace/update with explicit conflict behavior (`fail`, or conditional replace with ETag); avoid ambiguous overwrite defaults.
- Set maximum file size, bounded timeouts, and safe content type. Explicitly document content representation and size limits (text versus base64); do not pretend binary content is JSON text.
- Pagination and `nextLink` validation follow the same origin/host restrictions as Lists. No file deletion in the first release.

### Microsoft To Do

- Work only within the delegated signed-in user's accessible task lists. List/get/create/update; require task-list ID and task ID where applicable.
- Use a strict allowlist for writable task properties (for example title, body, due date, status, importance, reminder, and categories only after schema validation). Preserve omitted fields on PATCH and validate date/time zones.
- Do not expose app-only tasks or another user's data. No delete in v1.

## Shared execution/security requirements

- `capabilities: [credentials, http]`; fixed Graph v1.0 host, bounded requests/timeouts, bounded retries only for safe reads, no automatic retry of non-idempotent writes.
- Handle 401/403/404/409/412/429/5xx with safe messages; honor `Retry-After` for throttling with a bounded wait. Do not put response bodies, tokens, file content or personal data in logs/traces.
- Restrict response size, pages and item counts. Follow validated Graph pagination URLs only on the exact approved Graph origin. Never allow credential values or user inputs to redirect requests.
- Use synthetic fixtures only. Tests must cover authentication failure before HTTP, malformed inputs, successful reads/writes, pagination, throttling, ETag conflict, omitted PATCH fields, malformed responses, size caps, secret-free traces and repeat calls with different users/credentials.
- Tests using SDK fakes do not prove OAuth consent, persistent refresh-token rotation, UI selection or database authorization; platform integration tests and a development-tenant smoke test are mandatory.

## Delivery sequence

1. Platform team delivers and deploys Microsoft OAuth credential type, consent UX, refresh/token rotation, provider-aware SDK capability, exact credential resolution and integration tests.
2. Confirm tenant/app setup, supported permission set, OAuth account type, identity semantics and deployed SDK version.
3. Implement and test the three plugin nodes with the exact credential contract; publish a plugin PR.
4. Merge/release/activate only after platform prerequisites are satisfied; user/team administrators perform consent, bundle registration and activation.

## Open implementation decisions

- Whether personal and team OAuth credentials are both supported, and who owns the Entra app registration.
- Tenant-only versus multi-tenant account support; sovereign cloud support is out of v1 unless explicitly designed.
- Exact Graph endpoint permission matrix and whether Lists can be scoped more narrowly than site-wide permissions.
- File size cap and whether download output is text-only, base64, or a separate file/blob capability.
- Whether safe upsert is required in v1; create and update are independently supported either way.
