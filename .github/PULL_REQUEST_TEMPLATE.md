## Summary

Describe the behavior changed by this pull request.

## Motivation

Explain the contributor or maintainer problem this change addresses.

## Validation

List the focused and complete checks you ran.

```text
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
```

## Checklist

- [ ] The change is narrowly scoped to a linked issue.
- [ ] New behavior and failure modes have focused tests.
- [ ] User-facing behavior is documented.
- [ ] Unavailable evidence is not silently treated as a passing check.
- [ ] GitHub access remains read-only.
