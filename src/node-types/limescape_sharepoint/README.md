# SharePoint

One node for SharePoint sites, Lists and document libraries. Pick the operation with **Action**; the form only shows the fields that action uses. Output is `{"action": ..., "result": ...}` under the configured output key, or `{"error": ...}`.

| Action | Needs | Graph request |
|---|---|---|
| Search sites | Search text | `GET /sites?search=` |
| Get site by URL | Site URL | `GET /sites/{hostname}:/{path}` |
| List lists | Site ID | `GET /sites/{site}/lists` |
| List items | Site ID, List ID | `GET .../lists/{list}/items?$expand=fields` |
| Get list item | Site ID, List ID, Item ID | `GET .../items/{item}?$expand=fields` |
| Create list item | Site ID, List ID, fields | `POST .../items` |
| Update list item | Site ID, List ID, Item ID, fields | `PATCH .../items/{item}/fields` |
| Delete list item | Site ID, List ID, Item ID | `DELETE .../items/{item}` |
| List document libraries | Site ID | `GET /sites/{site}/drives` |
| List files | Site ID, drive ID, optional folder path | `GET .../root/children` or `.../root:/{path}:/children` |
| Search files | Site ID, drive ID, Search text | `GET .../root/search(q='...')` |
| Get file metadata | Site ID, drive ID, Item ID | `GET .../items/{item}` |
| Download text file | Site ID, drive ID, Item ID | `GET .../items/{item}/content` |
| Upload text file | Site ID, drive ID, file path, content | `PUT .../root:/{path}:/content` |
| Create folder | Site ID, drive ID, folder path | `POST .../children` |
| Delete file or folder | Site ID, drive ID, Item ID | `DELETE .../items/{item}` |

The usual way to find the IDs: **Get site by URL** (or **Search sites**) gives the site ID, then **List lists** or **List document libraries** gives the list or drive ID.

List actions follow Graph's next-page links up to **Maximum results** (1-1000, at most 10 pages) and return `{"value": [...], "truncated": bool}`. Next-page links are only followed when they point back to `graph.microsoft.com`.

Text transfer is UTF-8 only and capped at 1 MB each way; binary files are not supported. Uploading to an existing path replaces that file. Creating a folder that already exists fails instead of renaming. Delete actions remove one item by ID; SharePoint moves it to the site recycle bin. Updates use PATCH and can return 412 on ETag conflicts; writes are never retried.

Graph errors are returned as the HTTP status plus Graph's error code (such as `itemNotFound`), never the response body.

## Studio credential mapping placeholder

`node.py` defines `CREDENTIAL_TYPE` and `TOKEN_FIELD` as explicit `REPLACE_WITH_STUDIO_...` constants. Replace them with the exact credential type and token property supplied by Studio. The node asks the SDK to resolve the selected team or fixed personal credential, then sends only its access token to the fixed `graph.microsoft.com` v1.0 host. It does not implement OAuth or refresh. Do not replace the placeholders with secret values or put tokens in node parameters.

Requires delegated Graph permissions for the selected sites: `Sites.Read.All` for the read actions, `Sites.ReadWrite.All` for create, update, upload, folder and delete actions.

## Icon

`icon.svg` is the Microsoft SharePoint product icon from Microsoft's Fluent UI CDN (`brand-icons/product/svg/sharepoint_48x1.svg`), unmodified. It is a Microsoft trademark and is used only to show that this node integrates with SharePoint.
