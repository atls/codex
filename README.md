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
cd evals/model-fit && yarn install --immutable && yarn test
cd ../..
python tools/build.py
python -m unittest discover -s tools -p 'test_*.py'
```

GitHub Release attaches both archives at the declared version. Reusing an existing release version fails. See LICENSE for the existing BSD-3-Clause terms.
