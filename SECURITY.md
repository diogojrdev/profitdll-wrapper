# Security Policy

`profitdll-wrapper` handles brokerage trading credentials and order routing — security is a top priority.

This is an **unofficial** project, not affiliated with or endorsed by Nelogica.

## Supported Versions

| Version | Supported |
|--------|-----------|
| 0.1.x  | ✅        |

## Reporting a Vulnerability

**Do not open a public issue** for security vulnerabilities.

Please submit a private report to the maintainers:

1. Use GitHub's **"Report a vulnerability"** (Security Advisory) feature under the repository's Security tab, **or**
2. Create a private security advisory on GitHub.

Where possible, include:

- Description of the issue and potential impact.
- Steps to reproduce or a Proof of Concept (PoC).
- Affected versions and environment (OS, Python version).
- Suggested mitigation or fix, if available.

Expected initial response within **72 hours**. We will work with you on coordinated disclosure.

## Scope

We are particularly interested in:

- Credential leaks (username, password, activation key, routing keys).
- Memory corruption at the ctypes/DLL boundary that could be exploited.
- Flaws that allow executing orders or accessing data outside user intent.

## What is NOT a vulnerability

- API misuse by end-user application code (report as a standard issue).
- Licensing or redistribution issues regarding Nelogica's native DLL.

## Security Best Practices for Users

- Never commit credentials to version control; use environment variables (see `.env.example`).
- In production, validate strategies on simulator/demo accounts first.
- Keep Nelogica's native DLL updated to recommended releases.

