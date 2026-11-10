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

## Response

Do not announce assessment before its result. For an explicit assessment request, briefly report suitability or an unavailable source. For implicit use, a suitable profile or retained user choice does not require a separate message. Handle missing required sources as described above.

A useful recommendation identifies only the model, reasoning or speed changes that require action and their verified reason. Do not call an unknown active value unsuitable, enumerate the catalog or recommend more changes than the evidence warrants.

Link the official guidance used, separating its general advice from the task-specific conclusion.

An established root recommendation is the only response for that turn. End the turn without task tools or delegation. The exception is an explicitly enabled automatic Desktop pilot: it performs only the technical profile change and [handoff to the next turn](references/desktop-hook.md#automatic-handoff-to-the-next-turn), where the queued task starts on the target profile. In ordinary mode, resume in a new user turn after a profile change or explicit decision to keep the previous profile. This pause does not grant task admission; apply User choice after the user's decision.

A child recommendation is instead consumed directly when spawning that child.

For an authorized Desktop-hook connection or diagnosis on macOS, read [Desktop hook](references/desktop-hook.md). Selecting this skill does not enable hooks. If an automatic handoff is not confirmed, do not perform the original task on the previous profile.

When maintaining implementation, read the [code map](references/code-map.md).
