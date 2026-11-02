# Credentials and node types

Follow the source contract in the upstream Limescape plugin repository. Credential values are secret data. Never return, log or store them in node parameters. Validate exact credential type, mode, scope and schema before external I/O. OAuth refresh/consent is platform-owned; do not assume a new provider works with existing OAuth support. A manifest cannot register credential types. Document any platform migration or SDK prerequisite explicitly.
