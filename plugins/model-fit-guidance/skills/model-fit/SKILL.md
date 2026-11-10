---
name: model-fit
description: >-
  Recommend or allocate a suitable Codex model profile before complex
  development, architecture, instruction changes, review, remediation,
  investigation, publication, risky mutations, or long-running work, and
  before subagent allocation. Do not use for ordinary dialogue, explanations,
  short statuses, or simple low-risk edits without a subagent spawn; it never
  grants task admission.
---

# Model Fit

Read the [assessment policy](references/assessment-policy.md) before assessing a task.

## Explicit assessment

Use the installed CLI with JSON input as described in the [package README](../../README.md). Return the recommendation and its explanation. Ask for missing profile values instead of guessing. This distribution does not change the current chat profile or enable lifecycle hooks.
