# Desktop hook on macOS

Read this reference when connecting or diagnosing the Desktop hook or performing automatic handoff. Profile assessment alone does not require it.

## Connect

Install Vector Prime through Codex Desktop's native local marketplace. The plugin contains `.codex-plugin/plugin.json`, `hooks/hooks.json`, its Python package and this skill. To verify a local checkout:

```sh
codex plugin marketplace add .
codex plugin add vector-prime@atls-codex
```

Run `uv sync --locked` from the installed plugin directory. The supported compatibility manifest is used for Codex 0.166, whose portable manifest does not load plugin hooks. Hooks use Codex's `PLUGIN_ROOT`; their definitions are not copied into the user's `hooks.json`. Disable any previous Vector Prime integration when switching integrations so two handlers do not process one request.

Trust the exact definitions through `/hooks`, then inspect their sources and states through `hooks/list`. Inventory establishes discovery; an audit record for a specific turn establishes invocation.

Loaded sessions may retain an old handler. Before every callback and technical CLI command, the installed plugin rereads native config and `hooks/list`. Disabling the feature, plugin or exact hook stops automatic assessment and handoff without deleting state. Confirmed disablement permits ordinary work. Unavailable settings do not establish disablement or release earlier restrictions; technical tools are not started. An in-flight assessment can finish its external request, but the repeated admission check will not issue an obsolete handoff instruction.

The verified environment is macOS. Live config, authentication and `.tmp/` are local data outside the shared delivery. Verify candidates separately from working installations.

## Automatic handoff to the next turn

Once the user authorizes automatic handoff, the hook determines whether a profile change is needed. Follow the exact `additionalContext` instruction:

1. Run the supplied `assess` command. It reads the complete message accepted by Codex; UserPromptSubmit does not yet supply that native body. Task tools and the answer are guarded until assessment completes
2. For a recommendation, call the `codex_app` MCP server tool `mcp__codex_app__send_message_to_thread` (`codex_app.send_message_to_thread`), not its same-named dynamic app route for the same chat with the specified model/effort and service message
An explicit rejection of the dynamic route with “Use the codex_app MCP server” is not a failed MCP capability. Make one call through the MCP tool with the same prepared arguments. Do not retry a successful or uncertain switch, and do not queue after a rejected call.
3. Run the supplied `queue` command with unchanged arguments
4. End the technical turn. Perform the original task only in the confirmed continuation after the profile change

The utility obtains queue input from the native user message. Do not reconstruct it from text or ask the user to reattach media. The continuation is bound through native client message identity; edited queued input is assessed as accepted by the server. The runtime adds no service text to that input and does not rebuild attachments.

An ephemeral thread without native history access receives an assessment-unavailable warning; no autoswitch is claimed. A child's native `session_id` identifies its parent while `agent_id` identifies the actual executor. State, native input and audit are scoped to that executor. Child recommendations return to the parent allocator; automatic child-chat UI handoff is not claimed.

If a required tool or confirmed handoff is unavailable, report the reason. When Stop confirms no enqueue and resumes the original turn, respond to the original input on the active profile. An unavailable-context warning means the profile was not assessed. Runtime scenarios own guards and state: do not delete pending state or manually repeat queue add with an unknown outcome.

## Diagnose

Local audit: `$CODEX_HOME/.tmp/model-fit-hook-audit/<thread-id>.jsonl`. Correlate `turn_id`, event, outcome and reason code with native hook events. `executor_thread_id` owns the record; `root_session_id` preserves native parent identity.

`auto_assessed` records triage, profiles, input/context digests and assessment generation, not proof that a recommendation was applied. `auto_assessment_superseded` cancels only the old input's result; new state survives even with identical text and native turn ID. `SubmissionUnavailable` distinguishes a missing executor from a missing submission; an unknown turn stays `null`. Audit excludes raw input and tool arguments. Missing audit proves neither hook invocation nor profile suitability.

Check actual session cwd, hook source, enabled/trust state and handler loading before retrying. Hook inventory or a start message alone does not prove a profile switch.

External contracts: [Hooks](https://learn.chatgpt.com/docs/hooks) and [App Server](https://learn.chatgpt.com/docs/app-server). Native identity was checked against the [installed Codex implementation](https://github.com/openai/codex/blob/f79b26ccbb3116b052544666a181012fb45dc49b/codex-rs/core/src/hook_runtime.rs#L1095).

## Requirements discovered after reading sources

If reading a task or repository reveals materially changed requirements, record the requirements and source references in a local UTF-8 file without secrets. Use the same installed Python and Desktop CLI module to run `reassess --requirements-file <file>`, wait for completion and follow its result. This supplies additional assessment context: the runtime retrieves original native input, attachments and annotations itself. Do not pass IDs. Repeating `assess` for unchanged requirements reads the existing decision.

Reassessment is admitted only for the current admitted turn or a confirmed dequeued replay. A new submission supersedes the old result through generation. A missing or different native turn does not authorize assessment of old input. Manual profile choice retains its original scope.

The runtime records the observed profile after assessment. A native change before the next message becomes a fresh owner choice, including after keep when no queued handoff existed. This is not proof of suitability. Before returning an assessment, the runtime rereads the native profile; a concurrent change cancels the old recommendation while retaining the new choice, without assessing its suitability.

## Unknown assessment

`unknown` and handled evaluator failures preserve the current profile and allow ordinary work on the original request without establishing suitability. An old unqueued recommendation does not become a prohibition; new input and foreign generations are not overwritten. Errors have separate outcomes with safe types and failure locations, excluding exception messages. An unconfirmed outcome of an already-started queue operation remains a transport restriction: it does not permit another transfer.
