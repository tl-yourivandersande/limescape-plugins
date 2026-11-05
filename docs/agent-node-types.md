# Creating node types

Follow the source repository workflow and credential contract. Use `src/node-types/text_transform` as the minimal pattern. Codes must use this repository's `limescape_` prefix. Include manifest, implementation, Dutch and English translations, README and tests. Declare all capabilities and third-party dependencies. Test success, validation failures, external API errors, bounded pagination, safe output and secret-free errors.

For authenticated providers, a plugin cannot create credential types or implement OAuth lifecycle merely by selecting a credential. Verify exact SDK/platform support and document prerequisites. Never place client secrets or bearer tokens in node parameters.
