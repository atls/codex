# Model Fit for Codex Desktop

Two Desktop-only distributions share one assessment implementation:

| Distribution | Purpose |
| --- | --- |
| `model-fit-guidance` (Model Fit CLI) | Explicit skill/CLI assessment and a profile recommendation, without hooks or automatic switching |
| `model-fit` | The same assessor plus opt-in lifecycle hooks and native automatic handoff |

```sh
codex plugin marketplace add https://github.com/atls/codex.git
```

Use Codex's native plugin installation and hook trust controls. See [automatic setup](plugins/model-fit/README.md) and [standalone CLI](plugins/model-fit-guidance/README.md). Each plugin uses its own project environment; do not install the two Python distributions into a shared global environment.

The Directory submission is the CLI archive, marked Desktop only. Automatic-mode documentation is kept here in the repository. Public Directory submission, review and publication are separate steps from the source PR and GitHub Release.

Development evals and synthetic fixtures live under `evals/model-fit`. They are excluded from installation ZIPs. Private conversations, credentials, diagnostic corpora and real attachment payloads are never published.

## Build and verify

```sh
cd evals/model-fit && yarn install --immutable && yarn run test
cd ../..
uv run --project plugins/model-fit --locked python tools/build.py
uv run --project plugins/model-fit --locked python -m unittest discover -s tools -p 'test_*.py'
```

GitHub Release attaches both archives at the declared version. Reusing an existing release version fails. See LICENSE for the existing BSD-3-Clause terms.

## Source layout

Production scenarios live in `plugins/model-fit/src/assessment`, `submission`, `autoswitch` and `answer`. State transitions have one owner in `autoswitch/transitions.py`. Native Codex and filesystem implementations live under `infrastructure/adapters`; `entrypoints/cli` and `entrypoints/hooks` decode and compose their calls. Both distributions use the same assessment scenario.

`tools/build.py` reads plugin sources, manifests and LICENSE only. It builds without an `evals` directory. Evaluation fixture validation runs separately in the development suite. Public synthetic evaluations are grouped by scenario; their Promptfoo provider adapter lives under `evals/model-fit/infrastructure/adapters/promptfoo`. Private-corpus import, snapshot and trace-analysis tools are not part of this repository.

The Yarn runtime is the verified package/runtime pair installed by Raijin's public updater. Follow the [Raijin setup guide](https://github.com/atls/raijin/blob/master/docs/raijin/setup.md) for `yarn dlx @atls/raijin update`; commit its package, lockfile, configuration and runtime together.
