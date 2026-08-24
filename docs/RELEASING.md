# Release Process

ContribCheck publishes signed distributions to PyPI through GitHub Trusted Publishing. No PyPI password or long-lived API token is stored in the repository.

## One-time PyPI configuration

Create a pending Trusted Publisher on PyPI with these exact values:

| Field | Value |
|---|---|
| PyPI project name | `contribcheck` |
| GitHub owner | `gokul-debugger` |
| Repository | `contribcheck` |
| Workflow | `publish.yml` |
| Environment | `pypi` |

Create a GitHub environment named `pypi`. Add required-reviewer protection before publishing if the repository plan supports it.

## Release checklist

1. Confirm `main` is clean and CI is passing.
2. Set the same release version in `pyproject.toml` and `src/contribcheck/__init__.py`.
3. Update `uv.lock` when the project version or dependencies change.
4. Run the full local quality suite.
5. Build both distributions and inspect their contents.
6. Create an annotated `vX.Y.Z` tag from the intended commit.
7. Publish a GitHub release for that tag.
8. Wait for the `Publish to PyPI` workflow to finish.
9. Verify installation in a clean environment with `pipx install contribcheck`.

The workflow refuses to publish when the release tag and package metadata versions differ. PyPI does not permit replacing an uploaded version, so publish only from a reviewed commit.
