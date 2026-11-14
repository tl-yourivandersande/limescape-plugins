# Microsoft To Do

Lists tasks and gets, creates or updates a task in the specified task list. Create/update properties use JSON; updates accept only an explicit allowlist and PATCH preserves omitted fields. No delete operation is exposed.

The node uses a credential of the platform's **Microsoft 365 (OAuth2)** type `microsoft365OAuth2Api`, chosen in a dropdown with `[Team]`, `[Persoonlijk]` and `[Aanroeper]` choices like the built-in nodes. `[Aanroeper]` (stored as `@user:microsoft365OAuth2Api`) uses the credential of whoever starts the flow, so To Do acts for that person. For a code the node tries a team credential first and then a fixed personal one, so the deprecated `credential_mode` field is no longer used or shown. It resolves the credential with `oauth2=True`: the platform handles consent and token refresh and hands the node only `accessToken` and the credential's plain fields. This needs a platform version whose plugin credential capability supports every OAuth2 type. The node uses the delegated `/me/todo` Graph endpoints, so it acts as the person who authorized the credential. The type's default scope covers mail, calendar and contacts: set the credential's **Scope** to `Tasks.Read` or `Tasks.ReadWrite` as appropriate (`offline_access` is always added).

## Icon

`icon.svg` is the Microsoft To Do product icon from Microsoft's Fluent UI CDN (`brand-icons/product/svg/todo_48x1.svg`), unmodified. It is a Microsoft trademark and is used only to show that this node integrates with Microsoft To Do.
