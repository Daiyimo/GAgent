# Contributing

Start from `main`. Keep changes within one responsibility. Prefer pure functions
for parsing, validation and state transitions; keep network, files, device access
and clocks at explicit boundaries. Name the invariant before changing a protocol.

Never commit personal configuration, runtime data, credentials, signing material,
production logs or old private Git history. Use synthetic fixtures. Run the source
audit before committing and the relevant regression tests before submitting a PR.
The Android workflow builds both variants and audits the packaged contents.

Changes to official-service clients must work without privileged service keys.
New integrations are opt-in, validate TLS, fail closed when unconfigured, and
must not send a credential to a different origin during redirects or fallback.
Do not add automatic telemetry or download executable plugins into the app.

Describe the changed behavior, validation and remaining limitations. Dependency
updates must preserve upstream licenses and include a vulnerability review.
Contributions to project-owned code are accepted under Apache-2.0.
