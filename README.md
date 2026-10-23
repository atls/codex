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

Neither package includes user conversations, Thread Memory, credentials,
attachments, project hook definitions, or local audit data.

The source and both package archives use the [BSD 3-Clause License](LICENSE).
