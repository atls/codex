# Model Fit evaluations

These cases exercise the public Model Fit skill and the hook code without
publishing user conversations. The scenario inputs and answer examples are
synthetic. Run results, current source snapshots, model traces and token usage
are written under ignored `.tmp/model-fit-evals/`.

## Cases

| Case | Property checked |
| --- | --- |
| `backlog-read` | Judge the next read-only issue lookup, not the whole project |
| `issue-draft` | Explain any lighter model and effort choices independently |
| `local-search-design` | Ground an upgrade in the specific design work |
| `kubernetes-backlog` | Avoid a profile rule inferred from a technology name |
| `confirmed-choice` | Keep a profile explicitly chosen for the same work without a model call |
| `missing-source` | Return `unknown` when an obligatory source is unavailable |

The four first cases use a semantic grader with four criteria: nearest bounded
work, grounded profile change, separate model and effort reasoning, and no
universal technology rule. `behavior-calibration.json` contains synthetic
positive and negative examples for that grader. `answer-cases.json` checks a
separate text-only replay relevance classifier. The unit tests cover complete
queued input, images, state locks, error audit, project hook setup and privacy.

## Deterministic checks

From the repository root:

```sh
python3 -m unittest discover -s evals/model-fit -p 'test_*.py'
python3 tools/build.py
```

These commands do not require an OpenAI API key or a model inference request.
The test that inspects installed Codex hook definitions skips itself when the
CLI is unavailable. The build creates two ignored ZIP files under `dist/` and
verifies their contents.

## Live behavior evaluation

The following commands use the current Codex sign-in and consume model usage:

```sh
python3 evals/model-fit/run.py --controller --case backlog-read
python3 evals/model-fit/run.py --calibrate-behavior
python3 evals/model-fit/run-answer.py
```

`run.py` fetches current official OpenAI guidance and the local Codex model
catalog, runs each selected case in an isolated read-only app-server session,
and records exact source hashes and observed results. The grader checks the
meaning of the answer rather than requiring one model for every Kubernetes or
writing task. Evaluate a changed skill from that change's checkout; the
runner does not mutate working projects or publish results. Model failures
remain failures in the local manifest.
