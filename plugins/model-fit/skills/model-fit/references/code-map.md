# Код Model Fit

`pyproject.toml` связывает импорт `model_fit` непосредственно с `src/`.
Повторного каталога с именем skill нет. Пакет использует три фактически нужных
слоя: Application, Infrastructure и Entrypoints. Правила допустимости решения
относятся к прикладному контракту; отдельные domain entity/aggregate не вводятся.

| Путь в `src/` | Владелец и поведение |
| --- | --- |
| `api.py` | Публичный API переноса и совместимый экспорт оценки |
| `assessment.py` | Самостоятельная сборка оценщика без импорта Desktop и состояния переноса |
| `application/assessment/assess.py` | Оценка запроса: явный выбор, источники, prompt, evaluator, проверка решения |
| `application/assessment/contracts/` | Отдельные Profile, UserChoice, AssessmentRequest, Decision |
| `application/assessment/validation/` | Допустимость входа, текущего профиля и результата оценки |
| `application/assessment/ports/` | Источники, допустимость профиля по каталогу и evaluator во внутреннем языке оценки |
| `application/conversation/context.py` | Ограниченный контекст ближайшей работы |
| `application/handoff/lifecycle.py` | Единый владелец команд и сохраняемых переходов переноса |
| `application/handoff/` | Шаги подготовки, очереди и guards; сохраняют переходы только через Lifecycle |
| `application/handoff/requests/` | Внутренние Prompt, ToolCheck и AnswerCheck; исходный native event сохраняется opaque |
| `application/handoff/ports/` | Состояние, рекомендации, разговор, opaque input и представление результата |
| `infrastructure/assessment/` | Официальные источники, native catalog adapter, Codex preflight, events, CLI client и relevance check |
| `infrastructure/codex/` | JSON-RPC, auth copy, native conversation и input; перевод квитанции в Receipt |
| `infrastructure/handoff/` | JSON-файлы, flock, атомарная запись и адаптеры state/recommendation slots |
| `infrastructure/audit/` | Запись разрешённых диагностических полей |
| `entrypoints/assessment/` | JSON stdin/stdout CLI оценки и exit status |
| `entrypoints/desktop/` | Desktop CLI, native hook input/output, инструкции и связывание ручного prompt-hook |

Application импортирует только свои контракты и стандартные средства языка.
Файлы, RPC, clock, аудит и представление передаются через порты.
`api.py` и CLI выступают composition roots. Desktop input adapter переводит
служебные поля во внутренние requests; actions adapter распознаёт tool-вызов,
presentation adapter формирует только исходящий ответ. Передаваемые `context_reader`,
`assessor`, `native_factory`, `runtime_factory` сохраняют публичную форму API.
Native input остаётся непрозрачным; Model Fit не создаёт собственную модель медиа.

## Жизненный цикл переноса

`Lifecycle` — владелец переноса одного фактического исполнителя Codex;
родительский native session ID сохраняется только как происхождение. Его команды:
`submit`, `assess_submitted`, `prepare`, `enqueue`, `check_tool`, `finish`. Шаги используют его
операции `admit`, `stage`, `continue_transfer`, `begin_queue`, `receipt`,
`reject`, `confirm_queue`, `bind_replay`, `release`. Только этот компонент
пишет состояние через Store; Store обеспечивает flock и атомарную запись.
Generation сохраняется при переходах после удаления pending. Все записи результата
оценки проверяют принадлежность исходному submission; superseded — отмена старого
результата без изменения нового состояния.

| Состояние | Значение и завершение |
| --- | --- |
| отсутствует | Для запроса ещё нет решения или прежний перенос завершён и освобождён |
| submitted | Ожидает оценки принятого native input; повторный ввод меняет generation, прежняя оценка не может его заменить |
| passed | Текущий ход допущен; keep и неизвестная пригодность различаются assessment_decision |
| ready | Подготовлен перенос; технический ход может сменить профиль и вызвать queue |
| attempting | Native queue вызвана; до подтверждения исхода повтор запрещён |
| rejected | Получен подтверждённый отказ; новый запрос может начать новую оценку |
| queued | Получена квитанция; точный replay привязывается после проверки входа и профиля |

1. Native UserPromptSubmit → CLI → `Lifecycle.submit`: зарегистрировать только
   служебные поля и хеш, передать команду `assess`. Тело ещё не принято Codex;
   до оценки PreToolUse и Stop защищают предметную работу.
Контекст читается постранично, до четырёх страниц по пять ходов; точные
служебные control-only сообщения не вытесняют рабочие реплики. В ограниченный
контекст входят до восьми предыдущих рабочих ходов. Текущий ход, tool outputs
и reasoning исключены. Оценка учитывает явный выбор профиля и неудачи той же
незавершённой работы; короткая реплика не обнуляет эти условия.

2. `assess_submitted` читает полное принятое userMessage через native API.
   Assessment получает native input, task/context/profile и возвращает проверенное решение.
   Его runtime-адаптер создаёт временные workspace, private auth home и Codex
   process; после оценки закрывает процесс и удаляет временные ресурсы.
3. Keep допускает работу. Unknown не доказывает пригодность и сохраняет
   применимые запреты. Рекомендация готовит ready.
4. Технический агент применяет профиль через native Codex. `Lifecycle.enqueue`
   получает исходное сообщение, фиксирует attempting до внешнего вызова,
   проверяет квитанцию и полный input, затем подтверждает queued.
5. Следующая команда `assess` подтверждает replay по native client identity.
   Изменённое в очереди тело оценивается заново без замены исходной очереди;
   внешний выбор профиля сохраняется без утверждения о его пригодности. Старые технические
   инструкции завершаются. PreToolUse разрешает работу и запрещает повтор переноса.
6. Stop отменяет не поставленный ready; для bound replay выполняет отдельную
   ограниченную проверку релевантности. Она не является eval качества решения.
   При следующем запросе завершение queued сверяется с native history, затем
   Lifecycle освобождает прежний перенос. Неизвестный attempting не освобождается.

Hook только переводит native события и ответы. Он не читает файл состояния,
не выбирает модель и не определяет переход. Assessment не управляет очередью.
Native Codex владеет сессией, моделью и очередью; Model Fit владеет только
согласованием своего переноса. Audit не является источником восстановления.
`evals/model-fit` проверяет эти контракты отдельно и не входит в рабочий путь.

## API и совместимость

Поддерживаются `model_fit.api.assess`, `prepare_handoff`, `enqueue_handoff`,
`guard_tool`, `guard_replay_answer` и четыре типа assessment; SourceUnavailable экспортируется как типизированный отказ источников. Ручной assessment API, имена файлов состояния и порядок native input сохранены.
Автоматический CLI различает отсутствие submission, superseded и ошибку оценки;
отмена старой оценки возвращает контекст последнего ввода без команды переноса.
CLI: `scripts/triage.py`; `scripts/desktop.py hook|lifecycle|assess|prompt|queue`.
Внутренние Python-модули не являются дополнительным публичным API.
Нативное продолжение проходит через `submit_prompt` и `assess_submitted`;
низкоуровневый `prepare_handoff` не подтверждает новый replay по тексту.
Старые queued-записи без client identity остаются читаемыми до завершения
всех таких переносов; новые записи всегда сохраняют native client identity.

Assessment поднимает ValueError для неверного входа, SourceUnavailable для источников
и исходные runtime errors. CLI возвращает unknown/status 1 при невозможности оценки,
status 2 для неверного входа. Unknown не подтверждает пригодность профиля.
Самостоятельный wheel использует явный skill_directory либо установленный skill
из CODEX_HOME. Внутренние subprocess вызовы используют устанавливаемые Python-модули.

Старые Desktop scripts заменены единым CLI по принятому изменению команды запуска.
Все repository consumers используют новый вход. При установке plugin его skill и
`hooks/hooks.json` обновляются вместе до загрузки новых hook handlers;
работающий старый экземпляр сохраняет свой код до такого обновления.
Нативный допуск и ограничения отзыва описаны в [Desktop hook](desktop-hook.md);
их проверяет entrypoint до вызова прикладного Lifecycle.

Eval-сценарии и Promptfoo adapters живут в `evals/model-fit`. Production validator,
ожидания сценария и семантическая rubric имеют разные обязанности. Проверки,
их границы и команды описаны в README этого eval-проекта.
