# Contributing to Model Fit

Bug reports, documentation improvements, reproducible evaluation cases and focused code changes are welcome. This project follows the [ATLS contribution practices](https://github.com/atls/convention/blob/master/CONTRIBUTING.md) and repository issue/PR templates.

## Report a problem

Open an [issue](https://github.com/atls/codex/issues) with:

- Codex Desktop and CLI versions, operating system and installed Model Fit version
- Whether you used the explicit CLI or automatic hooks, and the configuration scope
- The task, active model/effort, expected behavior and observed behavior
- Minimal reproduction steps and sanitized error codes or audit references
- Whether a profile changed, input was queued, and the continuation actually ran

Keep tool-access problems, provider errors, model-selection quality and queue/replay transport distinct. Do not post tokens, authentication files, full private chats, raw logs with credentials or attachment payloads. A small synthetic example is more useful than an unreviewed conversation export.

## Set up an existing checkout

Use Node within `evals/model-fit/package.json`'s `engines.node` range, Git, Python 3.11+ and uv. Yarn is supplied by the committed verified Raijin package/runtime pair:

```sh
cd evals/model-fit
yarn install --immutable
uv sync --locked
yarn run test
```

To update the tooling pair, follow the [Raijin setup guide](https://github.com/atls/raijin/blob/master/docs/raijin/setup.md) and run `yarn dlx @atls/raijin update` from that Yarn project root. Commit its package, lockfile, configuration and runtime changes together; do not install an independent Yarn build.

## Build and verify the two packages

GitHub Actions assembles both distributions with the shared package action in
`.github/actions/package/action.yml`. Contents are declared in `.github/packaging`;
standard file tools copy sources and create ZIPs without rewriting instructions
or Python metadata. The release workflow publishes only after a confirmed PR
merge into master, using the exact merge commit.

Run the same composition commands and extracted-package checks locally:

```sh
cd evals/model-fit
yarn test:packaging
uv run --locked --no-editable --reinstall-package codex-model-fit mypy --strict --disallow-any-explicit -p model_fit
```

Packaging tests execute the action's actual shell commands in an isolated source
fixture without evaluation files. Native installation tests also build through
that action before testing cached hooks, trust and revocation. The Python package
uses the conventional `src/model_fit` layout and `uv_build` discovery.

## Change behavior carefully

Keep scenarios focused on a user's next task. Data declarations, protocols, exceptions and adapters should communicate their actual responsibility. Preserve manual profile choice, opaque native input, generation cancellation, one queue/replay cycle and conservative handling of unknown outcomes.

Use English for public documentation, skill instructions, production prompts and explanatory evaluation material. Support for users' other languages is a behavioral requirement to verify, not a reason to duplicate the runtime.

Run the relevant deterministic checks for a change. The public test suite makes no model calls. Native model evaluations are separate, require an existing local login and can consume account limits; see the [evaluation guide](evals/model-fit/README.md). Test automatic behavior only in isolated homes and owned test chats, not another person's working conversation.

## Python declaration layout

Keep declarations in a single `types/` directory under the scenario that owns their contract. Do not add subdirectories for dataclasses, protocols, dictionary declarations or aliases. The declaration itself shows its Python form; the path distinguishes declarations from executable logic. Create only the types actually consumed by that scenario.

For example, `application/switch/scenarios/finish.py` checks a completed answer; `application/answer/types/input.py` declares its input. Closely related companion declarations can share a module, such as a conversation protocol and its opening callback, or a decision dictionary and its Literal alias.

## Submit a change

Start with an issue, keep the scope focused, and use the repository PR template. Explain the user-visible behavior, reproduction or usage steps, validation and remaining limitations. Wait for CI, review and maintainer acceptance; a green run is not permission to merge or release.

The release workflow publishes only after a confirmed PR merge into master. Installing a candidate in a working launcher, publishing a GitHub Release and submitting to the OpenAI Directory are separate actions.
