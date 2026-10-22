# Security

Do not put credentials, exploit payloads containing private data, or production
logs in public issues. Report suspected vulnerabilities through the repository's
private vulnerability-reporting feature when enabled; otherwise contact the
maintainer privately before publishing details.

GAgent executes generated Python and operates the device with the user's granted
permissions. It is not a sandbox for hostile models, tasks, apps or plugins.
App-private storage protects against ordinary peer apps, not a compromised or
rooted device. Any code or key shipped in an APK can be extracted.

The loopback device bus requires a per-process random capability. Remote clients
do not receive this capability. WebView content is local; external links open
outside the privileged bridge. Server connections require normal TLS verification.
Service tokens are write-only in the integration settings response.

Official provider credentials, issuer keys, signing authority and proprietary
business implementations belong on servers. An installed client receives only
user-scoped, revocable credentials. Expiry, quotas and authorization must be
enforced by the server, even if the client has been modified.

`tools/audit_source.py` checks source, nested dependency archives and APK contents.
CI also scans Git history. These checks detect known patterns; they do not prove
that all possible sensitive data or vulnerabilities are absent. See
[the review record](docs/REVIEW.md) for the validation scope and dependency limits.
