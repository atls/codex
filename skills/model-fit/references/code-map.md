# Model Fit code map

The Python package uses the conventional `src/vector_prime` layout with uv_build.
Application owns behavior and its contracts. Infrastructure implements external
IO. Entrypoints decode commands/events, bind implementations and render output.

| Responsibility | Owning implementation |
| --- | --- |
| Register, start, evaluate, complete, fail, recover or reassess | `application/assessment/lifecycle.py` |
| Current-generation qualification | `application/assessment/guards/generation.py` |
| Request, decision and cache qualification | `application/assessment/constraints/` |
| Pure working-context assembly | `application/assessment/helpers/context.py` |
| Assessment inputs, results, profiles, evidence and cache port | `application/assessment/types/` |
| Plan and prepare a transfer; attempt, acknowledge, accept and confirm queueing | `application/handoff/lifecycle.py` |
| Reconcile queued input, replay identity and ownership | `application/handoff/lifecycle.py` |
| Transfer eligibility and continuation predicates | `application/handoff/guards/` |
| Phase-specific values and source references | `application/handoff/types/` |
| Refine compatibility snapshots into phase-specific values | `application/handoff/helpers/progress.py` |
| Atomic coordination of assessment/admission metadata | `application/switch/lifecycle.py` |
| Native submission, assessment, reassessment and completion orchestration | `application/switch/handlers/` |
| Tool admission and generation-safe recovery | `application/switch/admission/` |
| Pure admission predicates | `application/switch/admission/guards/`, `application/switch/guards/` |
| Accepted input inspection and hashing | `application/submission/helpers/content.py` |
| Opaque JSON/content validation | `application/submission/constraints/content.py` |
| Final-answer relevance | `application/answer/relevance.py`, `application/answer/prompts/`, `application/answer/decoding.py` |
| Explicit JSON assessment CLI | `entrypoints/cli/assess.py` |
| Hook event decoding/dispatch | `entrypoints/hooks/events/` |
| Technical assessment/queue commands | `entrypoints/hooks/handlers/` |
| Native tool-argument translation | `entrypoints/hooks/tool_action.py` |
| Filesystem executable identity checks before predicates | `infrastructure/adapters/runtime/executable_identity.py` |
| Native context, profiles, queues and assessment transport | `infrastructure/adapters/codex/` |
| Shared snapshot storage and compatibility decoding | `infrastructure/adapters/filesystem/state.py`, `state_codec.py`, `slot.py`, `store.py` |
| Assessment cache persistence | `infrastructure/adapters/filesystem/assessment_cache.py` |

## State and external effects

`ProcessSnapshot` is the shared compatibility record. Its phase, a UI setting or
a native acknowledgement alone does not establish a complete transfer.
`PreparedHandoff`, `AttemptedHandoff`, `AcceptedHandoff` and `QueuedHandoff` carry
phase-specific required data. Native source queries receive a `HandoffSource`
reference rather than the whole process snapshot.

The coordinator preserves generation and native owner scope. Assessment owns
its generation issuance and result validity. Handoff owns queue/replay rules.
The filesystem adapter validates stored shapes with Pydantic; application guards
qualify transitions. No second store, event-sourced reconstruction or internal
message bus is involved. Audit records observations and does not authorize work.

The owned lock spans bounded native queue IO. An attempt is durable before the
queue call. Every observed receipt identity is saved before checking its input.
Only a validated receipt produces AcceptedHandoff, which is required to confirm
queueing. Unknown external effects are not repeated. Source and authoritative
accepted-input digests remain separate because Codex may normalize local media
references. Attachments, annotations, ordering and opaque metadata are forwarded
without reconstructing the native input.

## Results and failures

Data declarations and behavioral protocols live in one flat `types/` directory
inside their owner. Pure utilities live in `helpers/`, qualification in
`guards/`, and input constraints in `constraints/`. Returned evaluation/queue
errors live in their owner's `errors/`; stopping exceptions live in
`exceptions/`. Provider RPC exceptions remain in the transport adapter.

Explicit assessment uses `vp`.
Automatic commands use `scripts/desktop.py`. These command
contracts do not expose internal Python layout as a second public API. Native
hook JSON is built at entrypoints from semantic application results.

An unavailable assessment preserves the current profile without claiming
suitability. Recovery requires the current generation and a safe process state.
An unresolved queue is a separate condition. Relevance checking detects answers
to another task; it does not grade solution quality.

Both decision schemas are generated through Pydantic from their declared data
contracts. Public synthetic evaluations and independent judge calibration live
under `evals/model-fit` and are not installed in either distribution.
