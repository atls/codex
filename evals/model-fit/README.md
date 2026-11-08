# Эвалы Model Fit

## Подготовка

Production runtime и hooks находятся в `plugins/model-fit`; skill содержит
инструкции в `plugins/model-fit/skills/model-fit`.

Требуются Node из диапазона engines.node, проверенная пара Raijin/Yarn, uv и существующий ChatGPT login. Codex CLI закреплён в devDependencies и устанавливается вместе с зависимостями.
`CODEX_EVAL_HOME` задаёт исходный login. При запуске eval auth копируется во
временный home с mode 0600; API-key providers отключены.

```sh
yarn install --immutable
uv sync --locked
```

## Запуск

Запускай команды из `evals/model-fit`:

```sh
yarn run test
CODEX_EVAL_HOME="$HOME/.codex" yarn validate
CODEX_EVAL_HOME="$HOME/.codex" yarn eval --no-table --output results/native.json
```

| Команда | Назначение |
| --- | --- |
| `yarn eval` | Native preflight по сценариям |
| `yarn eval:assessment` | Оценка профиля через production-сценарий |
| `yarn eval:ordinary` | Обычный диалог без автоматической оценки |
| `yarn calibrate` | Оценка зафиксированных calibration-примеров |
| `yarn eval:tasks` | Выполнение фиксированных задач |
| `yarn regrade` | Повторная оценка сохранённого результата оценки |

`MODEL_FIT_REGRADE_FILE` задаёт файл для повторной оценки сохранённого результата.

`yarn run test` запускает публичные проверки без model inference и без приватного корпуса. Fixtures проверяются отдельно от сборки пакетов. Инструменты импорта корпуса, snapshots и анализа SQLite-трасс в публичный репозиторий не входят.

## Приёмка native media

`yarn test:acceptance` проверяет native установку и допуск тестового plugin, grader и Promptfoo bridge через echo-provider,
без model inference. Для отдельного запуска native-host сценария выполни:

```sh
MODEL_FIT_ACCEPTANCE_OUTPUT=<private-output-directory> \
MODEL_FIT_IMAGE_PYTHON=<python-with-pillow> \
CODEX_EVAL_HOME=<existing-chatgpt-login> \
uv run acceptance/verify.py
```

Runner использует временный candidate home и scratch worktree.


Сквозные сценарии переноса находятся в
`evals/model-fit/autoswitch/tests/test_transfer_journey.py`: публичные команды
проходят оценку, реальное файловое состояние, очередь и replay. Подменяются
только context/assessment и native RPC; это не проверка исполнения моделей.
Отдельно проверяется, что неизвестный исход очереди запрещает повтор.
