# Security

This is a public repository.

Do not commit:

- broker logins or API keys
- personal account identifiers
- bank details
- private trade/account exports
- secrets, tokens, cookies, or session data
- `.env` files

The current codebase is paper-trading only and has no live-order execution path.

CI has read-only repository permissions. Ignore rules are safeguards, not secret detection: review every staged diff. Use synthetic fixtures only. Local journals, databases, credentials and private datasets must remain untracked. No broker adapter or credential configuration is provided.
