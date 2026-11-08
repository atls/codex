# Код Model Fit

`pyproject.toml` связывает импорт `model_fit` непосредственно с `src/`.
Код сгруппирован по выполняемым сценариям. Внешние операции находятся в
`infrastructure/adapters`, разбор и связывание входов — в `entrypoints`.

| Путь в `src/` | Поведение |
| --- | --- |
| `assessment/assess.py` | Явный выбор пользователя, источники, prompt, вызов оценщика и проверка решения |
| `assessment/validation.py` | Проверка запроса, активного профиля и решения |
| `assessment/contracts/` и `assessment/ports/` | Типы запроса и решения, контракты источников и оценщика |
| `submission/accept.py` | Регистрация нового native запроса |
| `submission/assess.py` | Чтение принятого ввода и выполнение его оценки |
| `submission/reassess.py` | Оценка изменившихся требований к текущему вводу |
| `submission/context.py` | Ограниченный контекст ближайшей работы |
| `autoswitch/prepare.py` и `autoswitch/apply.py` | Подготовка переноса и обработка решения |
| `autoswitch/enqueue.py` | Одна native постановка в очередь с проверкой квитанции |
| `autoswitch/guards.py` и `autoswitch/replay.py` | Допуск инструмента и продолжения |
| `autoswitch/transitions.py` | Единственная реализация сохраняемых переходов переноса |
| `autoswitch/requests/`, `contracts/`, `ports/` | Входы сценариев и нужные им контракты; native event остаётся opaque |
| `answer/check.py` | Проверка ответа связанного продолжения |
| `infrastructure/adapters/codex/` | Каталог, официальные источники, native history/input, RPC, оценка и временная auth-копия |
| `infrastructure/adapters/filesystem/` | Файлы состояния и рекомендаций, flock, атомарная запись и audit |
| `entrypoints/cli/assess.py` | JSON stdin/stdout CLI оценки и exit status |
| `entrypoints/hooks/` | Native hook input/output, Desktop CLI и композиция сценариев |

Сценарии получают только используемые зависимости явными аргументами.
Общего Dependencies и пересылающего вызовы Lifecycle нет. Исходный native event
передаётся context reader без потери неизвестных полей. Model Fit не создаёт
собственную модель медиа и не заменяет механизм сессий и очередей Codex.

## Переходы переноса

`autoswitch/transitions.py` владеет изменениями состояния одного фактического
исполнителя Codex; parent session ID сохраняется как происхождение.
Файловый адаптер обеспечивает блокировку и атомарную запись. Generation
сохраняется после удаления pending; устаревшая оценка не меняет новое состояние.

| Состояние | Значение и завершение |
| --- | --- |
| отсутствует | Для запроса ещё нет решения или прежний перенос завершён и освобождён |
| submitted | Ожидает оценки принятого native input; повторный ввод меняет generation, прежняя оценка не может его заменить |
| passed | Текущий ход допущен; keep и неизвестная пригодность различаются assessment_decision |
| ready | Подготовлен перенос; технический ход может сменить профиль и вызвать queue |
| attempting | Native queue вызвана; до подтверждения исхода повтор запрещён |
| rejected | Получен подтверждённый отказ; новый запрос может начать новую оценку |
| queued | Получена квитанция; точный replay привязывается после проверки входа и профиля |


`submission/accept.py` регистрирует служебные поля и digest и выдаёт команду
`assess`. `submission/assess.py` получает полный принятый userMessage через native
API, учитывает контекст и передаёт native input общему оценщику.
`autoswitch/prepare.py` и `apply.py` обрабатывают keep, unknown и рекомендацию.
Технический перенос применяет профиль через native Codex, затем `enqueue.py`
фиксирует attempting до внешнего вызова и проверяет квитанцию.

Продолжение связывается по native client identity, входу и профилю. Изменённый
в очереди ввод оценивается заново, внешний выбор профиля сохраняется.
`answer/check.py` выполняет ограниченную проверку релевантности bound replay;
это не оценка качества решения. Неизвестный attempting не освобождается
автоматически. Native Codex остаётся владельцем профиля и очереди;
audit не используется как источник восстановления.

## Запуск и проверка

Явная оценка: `model-fit` или `python -m model_fit.entrypoints.cli.assess`.
Автоматический CLI: `python -m model_fit.entrypoints.hooks.cli`
с командами `hook`, `lifecycle`, `assess`, `reassess`, `prompt`, `queue`.
Внутренние Python-пути не образуют дополнительный публичный API.

Неверный вход даёт status 2 без решения; невозможность оценки — unknown и status 1.
Unknown не подтверждает пригодность профиля. Временные ресурсы оценки закрываются
при завершении и ошибке. Самостоятельный wheel получает явный skill_directory
либо установленный skill из CODEX_HOME. Native допуск и отзыв описаны в
[Desktop hook](desktop-hook.md).

Публичные синтетические проверки находятся в `evals/model-fit` по сценариям;
адаптер Promptfoo — в его `infrastructure/adapters/promptfoo`.
Они не входят в установочные ZIP. Сборщик не читает eval fixtures.
