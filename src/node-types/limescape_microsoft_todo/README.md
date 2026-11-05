# Microsoft To Do

Lists tasks and gets, creates or updates a task in the specified task list. Create/update properties use JSON; updates accept only an explicit allowlist and PATCH preserves omitted fields. No delete operation is exposed.

Replace `CREDENTIAL_TYPE` and `TOKEN_FIELD` in `node.py` with the exact Studio credential type and access-token property. Studio is assumed to handle OAuth, consent and token refresh. The node uses the delegated `/me/todo` Graph endpoints, so credentials must carry `Tasks.Read` or `Tasks.ReadWrite` as appropriate.

## Icon

`icon.svg` is the Microsoft To Do product icon from Microsoft's Fluent UI CDN (`brand-icons/product/svg/todo_48x1.svg`), unmodified. It is a Microsoft trademark and is used only to show that this node integrates with Microsoft To Do.
