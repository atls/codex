# Model Fit implementation plan

Status: approved design; implementation in progress. Existing passing tests and
reviews establish the previous revision's behavior, not completion of this plan.

## Delivery

Continue issue #1 and PR #2, targeting master. Torin Asakura owns implementation
and acceptance. Codex implements the agreed work directly, without subagents.
Do not merge, install into working launchers, mutate working chats, or change
the daily corpus collector. Preserve the approved icon, authorship, license,
English product materials, contribution guide, and two Desktop distributions.

## Ownership and dependencies

Application owns scenarios and internal contracts. Infrastructure implements
those contracts. Entrypoints translate external calls and compose the executable.
Do not introduce an artificial domain layer, dependency bag, pass-through
lifecycle facade, event bus, or a second workflow engine.

| Owner | Responsibilities |
| --- | --- |
| assessment | Register, evaluate, reassess, complete and supersede assessments; context, profile choice, continuity, recommendation validity |
| handoff | Prepare, authorize, attempt, queue, retain receipt, bind continuation, reconcile and recover transfers |
| switch | Coordinate assessment and handoff; admission and completion of the automatic flow |
| submission | Accepted user content and exact identity; attachments, annotations, digests and service markers |
| answer | Relevance of the final answer to the current request |

Use application/assessment, application/handoff, application/switch,
application/submission and application/answer. Each owner has a flat types/
directory. Put pure utilities in helpers/, transition predicates in guards/,
input constraints in constraints/, returned failures in errors/ and stopping
exceptions in exceptions/. Related companion declarations may share a file.
Never disguise declarations or utility functions as product scenarios.

Assessment context assembly belongs to assessment/helpers/context.py; native
context acquisition belongs to the Codex adapter. Assessment completion must
not prepare a handoff. Reassessment and assessment recovery are operations of
the same assessment lifecycle, not independent scenario owners.

Hook event decoding and handlers belong to entrypoints/hooks/events/.
Codex stream response/notification handlers belong to the Codex transport's
events/. Keep direct calls between application lifecycles. Native PreToolUse
retains its external request semantics. Audit is observational, not a state
source or an internal delivery mechanism.

## API and state requirements

1. Assessment accepts an explicit complete request or a confirmed submission;
   registers a generation; evaluates outside long-held locks; completes only
   the current generation. An obsolete result returns Superseded without
   overwriting newer state. CLI assessment needs neither hooks nor handoff.
2. Handoff owns preparation through confirmation. Persist an attempt before
   bounded native queue IO; retain an observed receipt before payload checking.
   Keep the existing owned lock over that bounded IO until an independently
   verified fencing transition permits otherwise.
3. Definite queue rejection, uncertain transport, observed receipt and confirmed
   continuation remain distinct. Never blindly retry an uncertain effect or
   erase its identity when starting a new assessment.
4. Preserve exact native thread/turn/client identity, content order, attachments,
   annotations, text_elements and opaque metadata. Transport decoding must not
   silently strip unknown content or infer identity from adjacency.
5. Discussion, critique, corrections and omitted parts of previous work retain
   both current model and effort. Manual choice stays authoritative in its
   established scope. Explicit reselection and genuinely changed execution
   remain eligible. Uncertain relation does not authorize switching.
6. Assessment failure preserves the current profile without claiming suitability
   and permits ordinary work through current-generation recovery. An unresolved
   transfer has its own admission rules; do not conflate the two conditions.
7. Use explicit state variants with required fields internally. Decode legacy
   storage at the filesystem boundary. Do not invent missing identities or
   receipts. One atomic snapshot can contain separately owned assessment and
   handoff sections; native queue/profile state remains authoritative in Codex.
8. Render existing CLI/hook output only at entrypoints. Preserve public commands,
   output fields, error distinctions and native installation/trust semantics.

## Existing mechanisms

Use Pydantic for strict boundary validation, serialization and schema generation
from the agreed shapes. Keep business guards outside format validation. Use
dataclasses, enums and Protocol where appropriate; isolate opaque vendor JSON
instead of substituting Any for known internal shapes.

Use uv_build for conventional Python packaging and module discovery. Replace
covered custom mechanisms with maintained vendor/community implementations.
Evaluate the public Codex Python SDK separately for evaluator process/session,
requests, streaming and structured output. Adopt a covered unit after checking
its whole contract. Missing Desktop queue or input metadata support does not
justify retaining unrelated custom transport. Do not depend on private SDK APIs
or introduce another agent loop, account route or default bundled runtime.

Retain Promptfoo and the existing evaluation contracts. Inspect plugin-eval as
an additional development tool; evaluate its concrete static-report and
measurement coverage before integrating it. The hosted Evals platform shutdown
does not apply to this plugin. Preserve the already-used skill-creator validator
and make its invocation reproducible.

## Packaging and release

Remove tools/build.py and do not replace it with another custom assembler.
Declare package contents in .github/packaging/*.files. Use ordinary workflow
file-copy/archive tools for composition and ncipollo/release-action for release
publication. Publish only after a confirmed PR merge into master, checking out
the exact merge commit. Never publish on an arbitrary push.

Keep one assessment source and ready-to-copy entry instructions for each
distribution. Do not rewrite SKILL.md or pyproject.toml while packaging. Do not
make packaging depend on eval fixtures. Installed archives exclude tests,
evaluation tools, private-corpus tooling/data and generated local state.
Preserve direct project Yarn commands, Raijin-managed tooling and uv execution.

## Implementation sequence

- [x] Establish conventional Python source layout and build backend
- [ ] Implement complete assessment ownership and strict boundary forms
- [ ] Consolidate complete handoff ownership and state variants
- [ ] Implement switch coordination, submission ownership and pure admission
- [ ] Separate event boundaries, utilities, failures and composition
- [ ] Replace covered evaluator infrastructure with the public SDK
- [ ] Replace custom packaging with workflow composition and native release
- [ ] Validate plugin-eval and reproduce skill validation
- [ ] Complete behavior, typing, packaging and installed-fixture verification
- [ ] Publish current revision, pass CI and configured exact-head Codex review
- [ ] Finish cumulative self-review and present for user acceptance

## Acceptance evidence

Use the existing behavior suites and meaningful regression scenarios: generation
races, manual profile retention, parent/child ownership, complete input,
attempt/receipt ordering, uncertain queue outcomes, replay identity, technical
failure recovery, final-answer relevance, and native trust/revoke behavior.
Verify both extracted distributions, cold imports and actual packaged namespace.
Strict mypy rejects explicit Any in runtime; lint, formatting and diff checks
pass. Do not add filename bans, fixed test/scenario totals or implementation-
mirroring tests. Model runs are bounded to changed semantic behavior and tool
integration; preserve historical run evidence rather than relabeling it.

Completion requires both structural acceptance against this map and behavioral
evidence for the current published revision. Track unfinished work explicitly.
