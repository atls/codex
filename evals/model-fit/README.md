# Эвалы Model Fit

## Подготовка

Production runtime и hooks находятся в `plugins/model-fit`; skill содержит
инструкции в `plugins/model-fit/skills/model-fit`.

Требуются Node и Yarn из mise, UV, Codex CLI и существующий ChatGPT login.
`CODEX_EVAL_HOME` задаёт исходный login. При запуске eval auth копируется во
временный home с mode 0600; API-key providers отключены.

```sh
mise exec -- yarn install --immutable
uv sync --locked
```

## Запуск

Запускай команды из `evals/model-fit`:

```sh
mise exec -- yarn test
CODEX_EVAL_HOME="$HOME/.codex" mise exec -- yarn validate
CODEX_EVAL_HOME="$HOME/.codex" mise exec -- yarn eval --no-table --output results/native.json
```

| Команда | Назначение |
| --- | --- |
| `yarn eval` | Native preflight по сценариям |
| `yarn eval:controller` | Production controller |
| `yarn eval:ordinary` | Обычный диалог без автоматической оценки |
| `yarn calibrate` | Оценка зафиксированных calibration-примеров |
| `yarn eval:tasks` | Выполнение фиксированных задач |
| `yarn regrade` | Повторная оценка сохранённого controller result |
| `yarn eval:corpus` | Сравнение Model Fit и stock на выбранных snapshots |

`MODEL_FIT_REGRADE_FILE` задаёт файл для `regrade`. Для `eval:corpus` укажи
`MODEL_FIT_CORPUS_MANIFEST`; `MODEL_FIT_CORPUS_MANIFEST_SHA256` закрепляет его
ревизию. Запросы и snapshots корпуса не входят в репозиторий.

`yarn test` запускает Python и Node проверки без model inference. Чтобы выполнить
source-backed guard-тест, укажи `MODEL_FIT_CORPUS_ROOT`; без корпуса этот один
tест пропускается.

## Приёмка native media

`yarn test:acceptance` проверяет grader и Promptfoo bridge через echo-provider,
без model inference. Для отдельного запуска native-host сценария выполни:

```sh
MODEL_FIT_ACCEPTANCE_OUTPUT=<private-output-directory> \
MODEL_FIT_IMAGE_PYTHON=<python-with-pillow> \
CODEX_EVAL_HOME=<existing-chatgpt-login> \
uv run acceptance/verify.py
```

Runner использует временный candidate home и scratch worktree.


Сквозные сценарии переноса находятся в
`evals/model-fit/runtime/tests/test_transfer_journey.py`: публичные команды
проходят оценку, реальное файловое состояние, очередь и replay. Подменяются
только context/assessment и native RPC; это не проверка исполнения моделей.
Отдельно проверяется, что неизвестный исход очереди запрещает повтор.
