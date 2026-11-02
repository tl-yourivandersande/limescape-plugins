# Microsoft To Do

Lists tasks and gets, creates or updates a task in the specified task list. Create/update properties use JSON; updates accept only an explicit allowlist and PATCH preserves omitted fields. No delete operation is exposed.

Replace `CREDENTIAL_TYPE` and `TOKEN_FIELD` in `node.py` with the exact Studio credential type and access-token property. Studio is assumed to handle OAuth, consent and token refresh. The node uses the delegated `/me/todo` Graph endpoints, so credentials must carry `Tasks.Read` or `Tasks.ReadWrite` as appropriate.
