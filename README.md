# limescape-plugins

Open-source Limescape plugin node types for team `17` (bundle key: `team17`). Node codes use the `limescape_` prefix.

This repository is public. Never commit customer data, real identifiers, credentials or secrets.

## Microsoft Graph nodes

This repository contains initial nodes for [SharePoint (sites, Lists and document libraries) and Microsoft To Do](docs/microsoft-graph-integration.md). They use a credential of the platform's Microsoft 365 (OAuth2) type `microsoft365OAuth2Api`, resolved with `oauth2=True`: the platform refreshes the Graph token and the plugin never sees the refresh token or client secret. This needs a platform version whose plugin credential capability supports every OAuth2 type.

The initial scope supports SharePoint site lookup, List item read/create/update/delete, UTF-8 text file list/search/metadata/download/upload, folder creation and file delete; and To Do list/task read/create/update. Binary files and ETag conflict control remain follow-up work. These nodes need review, CI and a Studio smoke test before release/activation.

A release is made by merging reviewed code to `main` and tagging `vX.Y.Z`. Limescape administrators register the bundle source and activate each release; contributors do not merge or activate releases.
