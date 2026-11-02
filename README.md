# limescape-plugins

Open-source Limescape plugin node types for team `17` (bundle key: `team17`). Node codes use the `team17_` prefix.

This repository is public. Never commit customer data, real identifiers, credentials or secrets.

## Microsoft Graph integration design

The proposed SharePoint Lists, document-library and Microsoft To Do nodes are documented in [docs/microsoft-graph-integration.md](docs/microsoft-graph-integration.md). They are blocked on platform support for Microsoft OAuth consent and secure token refresh/rotation; the current SDK OAuth lifecycle documented to us supports Google Tag Manager only. This repository currently contains the design, not working Graph nodes.

A release is made by merging reviewed code to `main` and tagging `vX.Y.Z`. Limescape administrators register the bundle source and activate each release; contributors do not merge or activate releases.
