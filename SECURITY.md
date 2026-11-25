# Security

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability reporting on this repository
(Security → Report a vulnerability). You will get an answer within a few days.

## What J-Forecast Board is, and is not

It is a **single-user tool that runs on one PC**. It is not designed as a multi-user or internet-facing
service. Anyone who can sign in can use every feature, including changing the AI assistant and its
API keys.

## What is in place

| Area | Measure |
|---|---|
| Network exposure | Listens on `127.0.0.1` by default. Without sign-in (`JFB_AUTH=off`) it refuses to start on any other address. |
| Sign-in | Password stored as a scrypt hash with a random salt; random first password shown once; signed session cookie (`HttpOnly`, `SameSite=Lax`, `Secure` behind HTTPS) with a random key; constant-time checks; 5 failed attempts lock a client out for 60 s. |
| Browser | Content-Security-Policy without inline or remote scripts (one inline script allowed by hash), no `eval`; `X-Content-Type-Options`, `Referrer-Policy: no-referrer`, `X-Frame-Options: SAMEORIGIN`. |
| Cross-site requests | Changes sent from another site are refused (`Sec-Fetch-Site`, else `Origin`). |
| Uploads | Size limit (`JFB_MAX_UPLOAD_MB`), parsed in memory, never written to disk. |
| AI assistant | Off by default. External services need the user's consent for each destination. Private data never goes to them unless policy and a second confirmation allow it. CLI assistants run with no built-in tools (no shell, no files), only this app's tools, in an empty temporary folder; prompts go through stdin. The tools endpoint for CLI assistants answers only on this PC, never through a proxy, and only with the token of an open answer. |
| Secrets | Kept outside the program folder, `0600` on Linux; API keys are never returned to the browser; the audit log never stores prompts, data values or keys. |
| Supply chain | Pinned dependencies, `pip-audit` and `gitleaks` in CI and pre-commit; vendored Plotly recorded in `THIRD_PARTY_LICENSES.md`. |
| Errors | Unexpected errors answer with a generic message; details go to the console only. |

## What is not covered

- **Shared or hostile PCs.** Another program running as the same user can read the runtime folder.
- **Multiple users.** There is one account. There are no roles and no per-user data separation.
- **Exposure to the internet.** If you publish the board through a reverse proxy or a tunnel, keep
  sign-in on, use HTTPS, and set `JFB_TRUST_PROXY=1` only for a proxy on the same PC. Rate limiting
  beyond the sign-in lock-out is up to the proxy.
- **The AI providers.** What an external service does with the data it receives is governed by its
  own terms.
- **The model weights** are downloaded from Hugging Face; their integrity is checked by the
  `huggingface_hub` library, not by this app.
