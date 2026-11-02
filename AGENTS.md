# Coding-agent instructions

This repository contains dynamic node types for Limescape AI Platform.

## Read before implementing

1. Read README.md and CONTRIBUTING.md.
2. Follow docs/agent-node-types.md.
3. For authenticated integrations, read docs/credentials-and-node-types.md.

## Boundaries

- Node types live under `src/node-types/<code>/`.
- Use only the standard library, limescape_plugin_sdk, declared dependencies and relative helpers.
- Keep nodes stateless; never cache credentials or request data globally.
- Never log or return secrets or sensitive raw responses.
- Use bounded HTTP calls and safe errors.

## Credentials

Follow the documented credential modes and exact type/value schema. Do not put secrets in form fields. Verify the required platform/SDK support before claiming an integration is usable.

## Verification

Use Python 3.12 and follow docs/agent-node-types.md. Document tests actually run and outstanding activation prerequisites.
