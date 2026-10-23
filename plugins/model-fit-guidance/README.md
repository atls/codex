# Model Fit guidance

This package supplies the Model Fit selection skill for Codex. It evaluates the
next bounded task and explains a model or reasoning-effort recommendation using
the current Codex model catalog and OpenAI guidance. It does not install hooks,
change the active profile or replay a user request.

The package is generated from the shared selection rules in the public
[`atls/codex` repository](https://github.com/atls/codex).
Run `python3 tools/build.py` from the repository root to create the isolated
`dist/model-fit-guidance-0.1.0.zip` archive. The archive contains only its
manifest, this README, the generated skill and its UI metadata.

The full Codex Desktop implementation and opt-in setup live in the separate
[`model-fit` package](https://github.com/atls/codex/tree/master/plugins/model-fit).
Automatic switching is available only there; installing this guidance package
does not activate it.
