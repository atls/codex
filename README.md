# Vector Prime for Codex Desktop

**Choose a model for the work you are about to do, and keep your own choice in control.**

Vector Prime helps Codex decide when a task needs a more capable model, when a lighter profile is enough, and how much reasoning effort the next step warrants. You can ask for a recommendation explicitly or enable automatic assessment before work starts.

## Why it exists

Choosing the largest model for every task can make a short edit or check-in unnecessarily slow. Choosing a small model for work it cannot complete can cost more time in retries, broken tool access and manual recovery. A long conversation makes this harder: the next request may be a small summary even though the previous task was complex.

Vector Prime grew out of investigating those failures in everyday Codex work. It evaluates the **next piece of work**, its relevant context and the active profile. It uses OpenAI's model guidance and the models available in your local Codex installation. Model and reasoning effort are considered separately.

## What you can ask

Talk to Codex in your usual language. For example:

- “Use $model-fit to recommend a profile before we start this task”
- “This is only a short check-in from facts we already verified. Reassess whether a lighter model or less effort is enough”
- “The task now includes a risky migration and recovery planning. Reassess whether we need a stronger model”
- “I care more about finishing quickly than minimizing model cost”
- “Keep the model and effort I selected for this work”

These are requests and preferences, not magic commands that force one universal model. Codex can reassess when requirements change. The automatic integration applies a validated recommendation through Codex's native profile and queue mechanisms; the explicit CLI returns a recommendation for you to act on.

To require a specific available profile, select it in Codex or explicitly instruct Codex to use it. Ask for a fresh assessment when you want that choice reconsidered.

An explicit profile choice remains in effect for the same work until you revoke it. When requirements change, ask for a fresh assessment if you want that choice reconsidered. A failed hook, transport or provider request is not evidence that the model itself is too weak.

Questions, critique, corrections and missing parts of the previous result stay on the active model **and reasoning effort**. A short follow-up does not trigger an automatic downgrade. Ask explicitly to reconsider the profile when you want a different choice during that discussion; a genuinely new task can receive its own assessment.

## Choose how to use it

| Package | Everyday behavior |
| --- | --- |
| **Vector Prime CLI** (`vector-prime-guidance`) | Invoke the skill or CLI when you want advice. Receive a model/effort recommendation and explanation. No lifecycle hooks or automatic profile changes |
| **Vector Prime** (`vector-prime`) | Opt in to assessment before work. When a profile change is justified and supported, transfer the original native request to the next turn through the Codex queue |

Both packages use the same assessment rules and implementation. The CLI package is the Desktop-only Plugins Directory candidate. Directory submission and approval are separate from availability in this repository.

## Get started

You need an authenticated local Codex installation, Python 3.11+, Git and uv. This implementation targets Codex Desktop; it is not a cloud-chat integration.

**For explicit recommendations:** follow the [CLI installation and usage guide](#cli-reference). The installed `vp` command accepts JSON containing the task and authoritative active profile and returns a structured recommendation. You do not need to enable automatic hooks.

**For automatic handoff:** register this Git marketplace and follow the [automatic setup guide](docs/desktop-hooks.md):

```sh
codex plugin marketplace add https://github.com/atls/codex.git
codex plugin add vector-prime@atls-codex
```

Enable and trust the hooks only in the Codex configuration scope where you want automatic assessment. Keep the two plugin environments separate. After an update, already-loaded Desktop sessions may require a restart to load the new handlers.

## What happens during automatic work

1. Vector Prime reads the accepted native request and relevant context, including original attachments and annotations
2. A suitable profile keeps the work in the current turn. An uncertain assessment preserves the current profile and reports that suitability is unknown
3. A supported model/effort change produces a technical handoff: Codex changes the profile, queues the original input once, and continues it in the next turn
4. Queue and replay checks protect against duplicate transfers and stale assessment results. A bounded answer check detects some replies that have drifted to a different task

You should not have to retype the request or reattach an image just to change profiles. A queue acknowledgement alone is not proof that the work completed.

## Current scope and limits

- A recommendation does not guarantee task quality, lower latency or lower cost
- Automatic model/effort handoff depends on the native capabilities of the installed Codex version. Full automatic speed-tier changes are not implemented
- Ephemeral input and direct app-tool turns without lifecycle callbacks can be outside the supported history path
- A final-answer relevance check cannot undo tool actions that already happened
- The separately observed scheduled-heartbeat stale-replay issue is not fixed by this package

The verified local baseline is documented in the [automatic integration guide](docs/desktop-hooks.md). Report other environments and failures through [Issues](https://github.com/atls/codex/issues), including a minimal reproduction and version information.

## Help improve it

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, tests, bug reports and the PR workflow. Public synthetic evaluations are included for reproducibility.

Releases attach both versioned plugin archives. See [LICENSE](LICENSE) for the BSD-3-Clause terms.


## CLI reference

Desktop-only profile assessment using the local Codex installation. Requires Python 3.11+, Git, uv, and an authenticated Codex CLI. The command reads one JSON request from stdin and prints one decision as JSON.

```sh
uv run --project <installed-plugin-root> vp < request.json
```

```json
{"task":"Summarize the supplied release notes","active_profile":{"model":"gpt-6.1-sol","effort":"medium","speed":null}}
```

Supply the active profile from authoritative session state or an explicit user selection. Optional `context` carries relevant preceding work. Optional `input` carries original native Codex input items, including attachments; do not substitute attachment descriptions for the original input.

The evaluator is a separate local Codex process. The implementation temporarily copies local Codex authentication into an isolated home, never includes it in prompts or archives, and removes that temporary home on normal cleanup. It fetches official guidance and the local model catalog and consumes the signed-in account's model allowance.

Exit codes: 0 for a validated decision, 1 for unavailable assessment (`unknown`), 2 for malformed input. The CLI does not change the active profile, create a handoff, install hooks, or require pending hook state.

The archive includes the CLI runtime and the selection rules.

When the current speed is unknown, the evaluator output schema permits only null for active and recommended speed. A speed change from unknown state is rejected as UnknownSpeedChange; the CLI does not infer Standard or Fast. Known-speed assessment does not imply automatic Desktop speed switching.

Created by [Torin Asakura](https://github.com/TorinAsakura), published through ATLS. See the [product overview](https://github.com/atls/codex) and [contribution guide](https://github.com/atls/codex/blob/master/CONTRIBUTING.md).
