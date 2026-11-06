# Model Fit automatic integration

Desktop-only automatic assessment and native input handoff. Requires Python 3.11+, Git, uv and an authenticated Codex Desktop/CLI with plugin hooks and the native queue APIs used by this release.

Install `model-fit` from this repository's Git marketplace with `codex plugin add model-fit@atls-codex`. Enable `features.hooks = true` in the intended native Codex configuration scope. Review and trust the bundled UserPromptSubmit, PreToolUse and Stop definitions in Codex; installation alone does not grant hook trust. Enable the plugin only in the desired scope using native Codex configuration. Existing loaded sessions may need a Desktop restart after an update; confirm actual hook execution, not only inventory.

This package also exposes the standalone assessment command documented in the repository README. Both paths use the same assessor. The automatic path additionally owns submission state and native queue/replay checks, preserves an explicit user profile and passes original native input without rebuilding attachments.

Unknown assessment preserves the current profile and does not prove its suitability. Final-answer checking is a bounded text relevance check and cannot undo earlier side effects. Ephemeral thread input may be unavailable through the supported native API.

Public Directory review does not include this hook-bearing distribution. Installation and updates are explicit user operations; the CLI-only distribution does not install this one.

Local verification baseline: Codex CLI 0.167.0-alpha.3.2 and Codex Desktop 26.1029.61003 on macOS. Other Desktop versions require their own native capability check.
