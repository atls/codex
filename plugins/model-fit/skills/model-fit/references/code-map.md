# Model Fit code map

`pyproject.toml` maps `model_fit` directly to `src/`. Scenario names describe the work performed; native and filesystem implementations live under `infrastructure/adapters` and input composition under `entrypoints`.

| Responsibility | Implementation |
| --- | --- |
| Assess a task and profile | `assessment/assess.py`, `prompt.py`, `validation.py` |
| Assessment data and dependency declarations | `assessment/types/` |
| Typed assessment stop conditions | `assessment/exceptions/` |
| Register, assess or reassess accepted input | `submission/accept.py`, `assess.py`, `reassess.py` |
| Read relevant prior work | `submission/context.py` |
| Prepare profile handoff | `autoswitch/handoff/prepare.py`, `assessment_outcome.py` |
| Admit tools | `autoswitch/admission/check.py`, `autoswitch/admission/continuation.py` |
| Authorize a prepared transfer | `autoswitch/admission/authorization.py` |
| Retain prompt-hook recommendations | `autoswitch/recommendation/prompt.py` |
| Enqueue the accepted native input once | `autoswitch/handoff/enqueue.py`, `autoswitch/handoff/expiry.py` |
| Own durable handoff transitions | `autoswitch/state/transitions.py` |
| Accepted submission data | `submission/types/input.py` |
| Assessment callbacks | `submission/types/evaluation.py` |
| Native conversation and its opening contract | `autoswitch/handoff/types/conversation.py` |
| Recommendation persistence contract | `autoswitch/recommendation/types/storage.py` |
| Recommendation dictionary declaration | `autoswitch/recommendation/types/record.py` |
| Transaction storage and companion slot | `autoswitch/state/types/storage.py` |
| Handoff state and pending assessment | `autoswitch/state/types/record.py` |
| Typed submission stop conditions | `autoswitch/exceptions/` |
| Check a bound replay answer | `answer/check.py`, `limits.py`, `relevance.schema.json` |
| Native Codex profile/history/input and assessment IO | `infrastructure/adapters/codex/` |
| Locked atomic state, recommendations and audit | `infrastructure/adapters/filesystem/` |
| Explicit assessment CLI | `entrypoints/cli/assess.py` |
| Hook and technical CLI composition | `entrypoints/hooks/` |

The [Python declaration layout](../../../../../CONTRIBUTING.md#python-declaration-layout) distinguishes type-only modules from executable scenarios. Conversation and its opener share one contract module; transaction storage and its slot share another. Recommendation handling uses one thread-keyed storage contract. The scenarios receive explicit dependencies; there is no global Dependencies container or forwarding Lifecycle class. The original native event reaches the context reader without discarding unknown fields. Media remains opaque native input.

## State ownership

`autoswitch/state/transitions.py` owns changes for one actual Codex executor; parent session ID is provenance. The filesystem implementation owns locking and atomic persistence. Assessment generation survives removal of pending state. A superseded assessment cannot modify newer input.

| State | Meaning |
| --- | --- |
| absent | No decision exists, or a completed handoff was released |
| submitted | Accepted native input awaits assessment; new input changes generation |
| passed | The current turn is admitted; keep and unknown remain distinct |
| ready | Prepared handoff permits the technical profile switch and queue command |
| attempting | Native queue was called; repeating it is forbidden until its outcome is established |
| rejected | A confirmed queue rejection was received; a new request can start a new assessment |
| queued | A receipt exists; replay binds only after checking native input and profile |

Submission registers metadata and digests, then assessment reads the complete native userMessage. The shared assessor returns a validated decision. Handoff preparation processes that decision. Queue execution records attempting before the external call and verifies the receipt. The continuation binds by native client identity, accepted input and profile; edited queued input is reassessed, and native profile choice is preserved.

Answer checking is a bounded relevance check, not a quality grade. Unknown queue outcomes are not automatically released. Codex owns its profile and queue; audit is not a recovery source of truth.

## Entry points and errors

Explicit assessment: `model-fit` or `python -m model_fit.entrypoints.cli.assess`.
Automatic CLI: `python -m model_fit.entrypoints.hooks.cli` with `hook`, `lifecycle`, `assess`, `reassess`, `prompt` and `queue`. Internal Python module paths are not another public API.

Invalid input exits 2 without a decision. Unavailable assessment returns unknown and exits 1. Unknown does not establish suitability. Typed exceptions preserve distinct causes and caller handling; a technical relocation does not rename serialized diagnostic codes. See [Desktop hook](desktop-hook.md) for native admission and revocation.

Public synthetic evaluations are organized by scenario under `evals/model-fit`; their Promptfoo implementation is in `infrastructure/adapters/promptfoo`. They are not installed with either plugin. Fixture validation runs independently of package construction.
