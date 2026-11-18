# Changelog

## 0.1.1 - 2026-11-18

### Fixed

- Normalize right curly apostrophes (U+2019) before matching explicit work claims.
  Comments such as "I'd like to take this one" and "I'm working on this" are now
  recognized when typed using smart punctuation. Previously, an existing claim
  could be missed. See [PR #11](https://github.com/gokul-debugger/contribcheck/pull/11).
- Add regression coverage that keeps ownership questions, offers to help with
  tests, and quoted claims from being treated as explicit work claims.

No CLI, API, configuration, or dependency changes are required to use this fix.
