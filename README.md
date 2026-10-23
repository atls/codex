# ATLS Codex

Public Codex experiments and reusable packages from ATLS.

## Model Fit

Model Fit evaluates the next bounded task against the active Codex profile. The
full [Model Fit package](plugins/model-fit/README.md) adds an opt-in profile
handoff for Codex Desktop on macOS. Its runtime code, skill, schemas and local
hook setup live together under `plugins/model-fit/`.

The repository also builds a separate **guidance-only** package from the same
selection skill. That package recommends a profile and does not switch it or
install hooks. See [the eval suite](evals/model-fit/README.md) for synthetic
cases and the commands that run them.

The full package is distributed from this repository for manual Desktop
installation. OpenAI's public Plugins Directory currently excludes plugins
containing lifecycle hooks; the guidance-only ZIP is the candidate for that
directory. The ZIPs are separate products with separate behavior and review.
The [verification workflow](.github/workflows/verify.yml) builds both ZIPs on
each PR and master push and uploads them as a GitHub Actions artifact. OpenAI's
public directory still requires a separate package upload and review.
Locally, `python3 tools/build.py` writes versioned `dist/model-fit-*.zip` and
`dist/model-fit-guidance-*.zip`. The first copies the full plugin tree; the
second copies the shared skill up to its hook-specific section, then adds its
own manifest, README, icon and license. Tests inspect the exact ZIP members,
manifest identity, privacy boundary and byte-for-byte reproducibility;
`zipfile -t` checks archive integrity. CI uploads those same two files.

## Distribution and updates

The installable source under `plugins/model-fit/` is the primary GitHub
distribution. A user adds `atls/codex` as a Codex marketplace, installs the
plugin, and explicitly configures hooks for a selected project and thread.
After a new version is released, they refresh the marketplace and reinstall
the plugin; project-local hook definitions are reviewed and trusted again if
their commands changed. A CI artifact is only a downloadable build receipt,
not a plugin installation or a public release.

There are two separate OpenAI routes:

- [OpenAI Community Plugins](https://github.com/openai/community-plugins/blob/main/CONTRIBUTING.md)
  accepts external contributions through a fork and PR. A contribution needs
  the package source under `plugins/model-fit/`, its required Codex manifest,
  marketplace entry, cold-start guide, repository-specific master test suite,
  CLA and maintainer review. Their repository shape is adapted in the fork;
  the ZIP is not pushed there. We do not auto-push to that repository. An
  update is a new upstream PR based on a new version of this source.
- The [public Plugins Directory](https://developers.openai.com/plugins/deploy/submission)
  accepts a plugin ZIP through the submission portal. Only the separate
  `model-fit-guidance` archive is intended for that route. After publisher
  verification, upload the archive, resolve the portal's automated findings,
  submit for review, and publish the approved version. An update bumps the
  version, uploads a new complete ZIP, and passes the portal checks again.

The official [`openai/codex-action`](https://github.com/openai/codex-action)
runs Codex in GitHub Actions using an API key; it does not package plugins.
This repository's build script creates the two archives without an API key.
For an update, change the source and the affected manifest version(s), run the same
checks, publish the new Git marketplace revision, and then submit separate
upstream Community Plugins PR and Directory ZIP update as applicable. Neither
OpenAI channel is updated merely because this repository's CI passed.

Neither package includes user conversations, Thread Memory, credentials,
attachments, project hook definitions, or local audit data.

The source and both package archives use the [BSD 3-Clause License](LICENSE).
