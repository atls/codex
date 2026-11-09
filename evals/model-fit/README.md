# Model Fit Evaluations

## Setup

Production runtime and hooks live in `plugins/model-fit`; the skill instructions are in `plugins/model-fit/skills/model-fit`.

Requirements: Node within the package's `engines.node` range, the verified Raijin/Yarn pair, uv, and an existing ChatGPT login. Codex CLI is pinned in `devDependencies` and installed with the project dependencies. `CODEX_EVAL_HOME` selects the source login. Evaluation copies its authentication file into a temporary home with mode 0600; API-key providers are disabled.

```sh
yarn install --immutable
uv sync --locked
```

## Run evaluations

Run commands from `evals/model-fit`:

```sh
yarn run test
CODEX_EVAL_HOME="$HOME/.codex" yarn validate
CODEX_EVAL_HOME="$HOME/.codex" yarn eval --no-table --output results/native.json
```

| Command | Purpose |
| --- | --- |
| `yarn eval` | Native preflight against the assessment scenarios |
| `yarn eval:assessment` | Assess a profile through the production assessment scenario |
| `yarn eval:ordinary` | Ordinary dialogue without automatic assessment |
| `yarn calibrate` | Evaluate the saved calibration examples |
| `yarn eval:tasks` | Execute the defined tasks |
| `yarn regrade` | Regrade a saved evaluation result |

Set `MODEL_FIT_REGRADE_FILE` to select the result to regrade.

The ordinary-dialogue trace assertion requires available native events without tool activity. The existing semantic rubric grades the answer and unsolicited profile advice separately.

`yarn run test` runs the public checks without model inference or a private corpus. Fixture validation runs independently of package construction. The public repository does not contain tools for importing private corpus data, managing snapshots, or analyzing SQLite traces.

## Native media acceptance

`yarn test:acceptance` checks native installation, test-plugin admission, the grader, and the Promptfoo bridge through the echo provider. It makes no model calls. To run the separate native-host scenario:

```sh
MODEL_FIT_ACCEPTANCE_OUTPUT=<private-output-directory> \
MODEL_FIT_IMAGE_PYTHON=<python-with-pillow> \
CODEX_EVAL_HOME=<existing-chatgpt-login> \
uv run acceptance/verify.py
```

The runner uses a temporary candidate home and scratch worktree. It exercises the unavailable-source fallback only when the zero-turn capability probe observes that boundary. If the boundary is absent, it records not_applicable without model execution or a passing acceptance claim. The deterministic suite also sends a complete synthetic provider record through the real Promptfoo Python-grade bridge; that validates the bridge, not native model execution.

The handoff scenarios are in `evals/model-fit/autoswitch/tests/test_transfer_journey.py`. They check the public commands, persistent local state, queueing, and replay. Assessment and context are controlled, as are native RPC calls; these tests do not measure model execution. The suite also checks that an unknown queue outcome prevents a retry.

## Language validation

`fixtures/language-validation.json` records bounded English/Russian synthetic inputs and observations before and after translating the shared instructions. Russian text in those explicitly localized inputs is intentional. Both languages use one maintained assessment implementation; no duplicate runtime port is implied.

The recorded times are elapsed assessment calls, including setup and provider variability, not task-completion or model-latency benchmarks. Reproduce a case by passing its input JSON to the installed explicit CLI with the recorded evaluator model/effort. Native evaluations require a local login and consume model usage. Decision-class preservation is an observation, not a universal correct-model label.
