# Model Fit CLI

Desktop-only profile assessment using the local Codex installation. Requires Python 3.11+, Git, uv, and an authenticated Codex CLI. The command reads one JSON request from stdin and prints one decision as JSON.

```sh
uv run --project <installed-plugin-root> model-fit < request.json
```

```json
{"task":"Summarize the supplied release notes","active_profile":{"model":"gpt-6.1-sol","effort":"medium","speed":null}}
```

Supply the active profile from authoritative session state or an explicit user selection. Optional `context` carries relevant preceding work. Optional `input` carries original native Codex input items, including attachments; do not substitute attachment descriptions for the original input.

The evaluator is a separate local Codex process. The implementation temporarily copies local Codex authentication into an isolated home, never includes it in prompts or archives, and removes that temporary home on normal cleanup. It fetches official guidance and the local model catalog and consumes the signed-in account's model allowance.

Exit codes: 0 for a validated decision, 1 for unavailable assessment (`unknown`), 2 for malformed input. The CLI does not change the active profile, create a handoff, install hooks, or require pending hook state.

The archive includes its runtime and selection rules. Developer evals, benchmarks and the private corpus are not installed. Public Directory upload/review remains separate from a GitHub Release.

When the current speed is unknown, the evaluator output schema permits only null for active and recommended speed. A speed change from unknown state is rejected as UnknownSpeedChange; the CLI does not infer Standard or Fast. Known-speed assessment does not imply automatic Desktop speed switching.
