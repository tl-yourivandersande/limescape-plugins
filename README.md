# limescape-plugins

Open-source Limescape plugin node types for team `17` (bundle key: `team17`). Node codes use the `team17_` prefix.

This repository is public. Never commit customer data, real identifiers, credentials or secrets.

## Microsoft Graph nodes

This branch adds initial nodes for [SharePoint Lists, document libraries and Microsoft To Do](docs/microsoft-graph-integration.md). They assume Studio resolves a Microsoft OAuth credential to a current Graph access token; OAuth and token refresh are not implemented in the plugin. The exact Studio credential type and access-token property are explicit placeholders in each node and must be mapped before execution.

The initial scope supports List item read/create/update; UTF-8 text file list/metadata/download/upload; and To Do list/task read/create/update. Pagination, binary files, ETag conflict control and the exact Studio credential mapping remain follow-up or verification work. These nodes need review, CI and a Studio smoke test before release/activation.

A release is made by merging reviewed code to `main` and tagging `vX.Y.Z`. Limescape administrators register the bundle source and activate each release; contributors do not merge or activate releases.
