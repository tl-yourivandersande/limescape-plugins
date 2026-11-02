# SharePoint List

Reads list items, reads one item, creates an item (`fields` JSON object), or updates an item by ID. Output is the Graph response under the configured output key. This first cut is one Graph page per request; pagination support is a follow-up before production use.

## Studio credential mapping placeholder

`node.py` defines `CREDENTIAL_TYPE` and `TOKEN_FIELD` as explicit `REPLACE_WITH_STUDIO_...` constants. Replace them with the exact credential type and token property supplied by Studio. The node asks the SDK to resolve the selected team or fixed personal credential, then sends only its access token to the fixed `graph.microsoft.com` v1.0 host. It does not implement OAuth or refresh. Do not replace the placeholders with secret values or put tokens in node parameters.

Requires delegated Graph permissions appropriate to the selected site/list. Updates use PATCH and can return 412 on ETag conflicts. No delete or implicit upsert.
