# Security Policy

## Reporting a Vulnerability

Please do not open a public issue for a vulnerability involving token exposure or unauthorized GitHub access. Contact the maintainer through the private security advisory feature on GitHub.

## Token Handling

ContribCheck only needs read access to repository metadata. Use a fine-grained token with the minimum permissions required for the repositories being inspected.

The CLI reads `GITHUB_TOKEN` from the process environment. The HTTP service accepts a bearer token for a single request or uses its own environment token. ContribCheck does not persist tokens or include them in reports.
