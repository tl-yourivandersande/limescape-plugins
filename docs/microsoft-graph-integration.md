# Microsoft Graph: Lists, document libraries and To Do

**Status:** plugin design based on the user-provided assumption that Studio already creates Microsoft OAuth credentials and supplies a valid, refreshed Microsoft Graph access token at execution time. This OAuth lifecycle is external to these plugin nodes. The exact Studio credential type/value contract still must be matched when implementing and tested in the target environment.

## Goal and boundary

Provide three focused flow nodes, backed by Microsoft Graph and one shared token-consumption helper:

| Node code (proposed) | Resource | Initial operations |
|---|---|---|
| `team17_sharepoint_list` | SharePoint Lists | List items with pagination; get item; create item; update item by ID. Optional upsert only if uniqueness and race behavior are documented. |
| `team17_sharepoint_file` | SharePoint document libraries (Graph drives) | List/search files, get metadata, download file content with documented representation, upload/create, update/replace content, optionally create folder. No delete in v1. |
| `team17_microsoft_todo` | Microsoft To Do | List task lists and tasks; get task; create task; update task. No delete in v1. |

Names are proposals, subject to checking reserved SDK node codes and the installed catalog before implementation. Inputs must be flow-friendly JSON; outputs must be stable JSON and avoid returning opaque Graph response fields by default. Keep each node stateless.

## Authentication contract (assumed Studio responsibility)

For this plugin design, assume Studio's configured Microsoft OAuth credential resolves at runtime to a **currently valid access token for Microsoft Graph**, with consent, refresh-token rotation, secure persistence and revocation handled by Studio/platform. Plugin nodes only read the resolved credential for the selected mode and send its access token as a Bearer token to the fixed Graph v1.0 API host. They never implement OAuth consent or refresh, and never receive/store refresh tokens or client secrets.

The plugin must not place tokens in parameters, outputs, logs or traces. The exact credential type name, selection modes, access-token value key and runtime resolver call are deployment contracts to confirm during implementation. A fake-context unit test cannot establish the platform actually refreshes tokens; a development-environment smoke test must verify that it supplies a valid token on successive runs and handles revocation safely. If the Studio credential is already available with this contract, **no new OAuth feature or token-refresh platform work is in scope** for this plugin.

Credential selection should use the modes supported by Studio: selected team credential, selected personal credential, or caller-specific personal credential type only if the corresponding resolver/identity behavior is available. Do not assume one mode works for all team setups. Never fall back silently between users or personal/team credentials.

## Microsoft Entra registration and permissions

Use delegated permissions for the initial release: To Do operations are user-context operations and delegated credentials naturally constrain SharePoint access to the authenticated account. The Studio administrator must configure the appropriate Entra application/account type, consent and Graph permissions. Verify exact endpoints and least-privilege scope options against current Microsoft Graph documentation before implementation; do not claim `Sites.Selected` works for every delegated Lists endpoint without validating its semantics.

Candidate scopes to validate:

- Lists: `Sites.Read.All` for read-only and `Sites.ReadWrite.All` for create/update, subject to endpoint-specific least-privilege options.
- Libraries: `Files.Read` / `Files.ReadWrite` for the signed-in user's files, or corresponding `Sites.*` scope for site drives; select according to endpoint and intended site scope.
- To Do: `Tasks.Read` / `Tasks.ReadWrite` delegated permissions. Do not use app-only access implicitly.

Request incremental scopes if Studio supports that. Separate read-only and write permissions where practical. Any tenant-wide access beyond the user's intended scope must be explicit and administrator-approved.

## Node contracts

### Lists

- Select site and list by validated ID (or a separately resolved, non-ambiguous display-name lookup); never accept arbitrary request URLs.
- Create/update accept explicit `fields` objects and optionally item ID. Validate JSON object type, field count/size and reserved/system fields. Inputs may not set URL/host or auth headers.
- Upsert is not an atomic Graph primitive. Prefer separate create and update operations initially. If upsert is added, query an indexed key, handle zero/multiple matches explicitly, and document race/idempotency behavior.
- Handle `@odata.nextLink` with page caps and same-origin validation; project only requested fields. Respect `If-Match`/ETag for safe updates when supplied; map 412 conflicts to safe errors.

### Document libraries

- Require site/drive identifiers and a path/item ID; derive URLs only from fixed `graph.microsoft.com` endpoints and validated, encoded path segments.
- Support create-new and replace/update with explicit conflict behavior (`fail` or conditional replace with ETag); never overwrite ambiguously by default.
- Set maximum file size, bounded timeouts and safe content type. Document content representation and size limits (text versus base64); binary data is not JSON text.
- Pagination and `nextLink` validation follow the same origin restrictions as Lists. No deletion in v1.

### Microsoft To Do

- Operate only on task lists accessible to the credential's signed-in user. List/get/create/update; require task-list ID and task ID as appropriate.
- Strict allowlist of writable properties (for example title, body, due date, status, importance, reminder; categories after schema validation). Preserve omitted fields on PATCH and validate date/time zones.
- Never expose another user's tasks. No delete in v1.

## Shared execution and security requirements

- Declare `capabilities: [credentials, http]`; fixed Graph v1.0 host, bounded requests/timeouts, bounded retries for safe reads only, and no automatic retry of non-idempotent writes.
- Handle 401/403/404/409/412/429/5xx with safe messages; honor `Retry-After` with a bounded wait. Do not log response bodies, tokens, file content or personal data.
- Restrict response size, pages and item counts. Follow validated Graph pagination URLs only on the approved Graph origin. Never allow credential values or user inputs to redirect requests.
- Synthetic tests cover credential failure before HTTP, malformed inputs, successful reads/writes, pagination, throttling, ETag conflict, omitted PATCH fields, malformed responses, size caps and secret-free traces. Include repeat runs with different credential references to detect leakage.
- A development Studio smoke test must validate the actual credential type/value shape, token audience/expiry/refresh behavior and scopes. If that smoke test shows the assumed contract is absent, pause implementation and report the concrete mismatch rather than embedding OAuth into the plugin.

## Delivery sequence

1. Confirm the actual Studio Microsoft credential type, access-token field mapping and supported credential selection mode in the target environment. This is contract verification, not a request to build new OAuth support.
2. Confirm tenant/app registration and delegated permissions for the selected Graph endpoints.
3. Implement and test the three plugin nodes with the Studio-resolved access token. Run unit tests and a development-tenant smoke test for reads and writes.
4. Review, merge, release and activate the plugin bundle; user/team administrators handle Studio consent/configuration and Limescape bundle activation.

## Open implementation decisions

- Exact Studio credential type name and access-token property/value shape; selected team vs personal modes and whether a caller-specific mode is exposed.
- Tenant-only versus multi-tenant account support; sovereign cloud support is out of v1 unless Studio and Graph host configuration already support it.
- Exact Graph endpoint permission matrix and whether Lists can be scoped more narrowly than site-wide permissions.
- File size cap and whether download output is text-only, base64, or a separate file/blob capability.
- Whether safe upsert is required in v1; create and update are independently included.
