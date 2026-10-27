# Частичные результаты (Stage 2.6, кандидат)

По умолчанию работает прежний режим. Для проверки нового пути:

```console
uv run localocr convert "папка" --use-config --fail-soft
```

`--no-fail-soft` явно выключает его, включая сохранённое значение из конфигурации.
В простом и полном GUI: «Сохранять частичные данные (fail-soft)». Настройка
`fail_soft` по умолчанию false; старые JSON совместимы. GUI и CLI вызывают один
сервис; код выхода CLI 1 для PARTIAL/REVIEW ожидаем.

Результаты остаются в `results/`. Проверяемые таблицы имеют листы «Таблица N»;
геометрия на изображении не считается подтверждённой. Остальной текст сохраняется
на «Неразмещённые данные», а текст без таблиц — на «Распознанный текст», по исходным
строкам в A. «Проверка» открывается первой. Salvage никогда не SUCCESS.
`XLSX_WITH_DATA` означает наличие наблюдений после readback, не точность OCR.

Все значения нового режима — текст, включая формулоподобные строки, даты,
десятичные разделители и ведущие нули. Недопустимые XML символы обратимо
представлены как `\uXXXX`, исходный обратный слеш удваивается. Длинная строка
разбивается на последовательные ячейки A с явным предупреждением. Слишком
большие структурные гипотезы переходят в текст; абсолютные лимиты ответа и числа
строк дают явный отказ без публикации повреждённой книги.

`report-*.json`, `summary.json/csv` и `jobs.jsonl` содержат статусы, причины и
метрики. Технический sidecar отказа — `diagnostics/failures/` рядом с exe
(в source — корень checkout). Сырой OCR сохраняется только при `--diagnostics`,
также рядом с exe; это приватные данные. Не включайте их в публичный Review ZIP.
Reasoning, явные служебные envelopes, активный HTML и вырожденные повторения
отфильтровываются детерминированно. Короткое слово `Error` внутри валидной таблицы
сохраняется. Для произвольного текста невозможно доказать его происхождение
одним parser; необходима проверка изображения человеком.

Выбранные сервер и model ID не меняются. Для ID с `deepseek-ocr` используется
Markdown prompt, для остальных — прежний Table Recognition. Настоящий OpenWebUI
DeepSeek smoke ещё необходим (SERVER_PENDING). Нет автоматического перехода с
сервера на Embedded. Embedded веса и Auto/GPU/CPU сохранены.

Нативный llama-server работает отдельным процессом, один inference slot. Новый
режим закрывает его после ошибки, перезапускает перед следующим файлом и после
16 успешных ответов. На POSIX собственная группа завершается TERM→KILL с grace
2 секунды; на Windows предусмотрено завершение дерева собственного живого PID.
Windows и frozen process-tree semantics требуют отдельной квалификации.
Ollama/OpenWebUI остаются HTTP transport; их процессы приложение не завершает.

Запись: временный XLSX в той же директории → readback значений, формул и merges
→ проверка отмены/источника → атомарная публикация. Без overwrite существующая
книга защищена. RUNNING/порванная запись журнала не cache hit; digest, параметры,
prompt, pipeline и источник участвуют в fingerprint. Без доказанного digest
межзапусковый resume отключён. Отмена не считает ещё не начатые файлы FAILED.

Это кандидат для проверки, PRODUCT_RELEASE=NO_GO. Обработка native crash/timeout
проверяется отдельными тестовыми процессами; произвольный Python parser/writer
не имеет принудительного process deadline. Реальная Windows Portable
квалификация и приёмка владельцем остаются обязательными.

## Stage 2.7 corrective (квалификация, не релиз)

В opt-in сервисе OCR остаётся на выбранном provider. Полученный ответ передаётся
через transient private spool в один отдельный owned parser/writer процесс;
повторного inference или загрузки модели ради postprocessing нет. Parser получает
10 секунд с запуском процесса, writer — 30 секунд, общий cap — 40 секунд плюс
ограниченное завершение owned процесса. Результат IPC — не более 64 KiB metadata;
родитель проверяет SHA готового файла, source и cancel и только затем публикует
XLSX эксклюзивным hard link либо os.replace при явном overwrite.

На Linux worker ограничен 2 GiB address space, 64 MiB размером файла и 45 CPU
секундами. На Windows Job Object ограничивает committed memory 2 GiB и закрывает
дерево при закрытии handle. Запуск suspended, назначение job до resume; отказ
назначения не включает слабый PID fallback. POSIX leader удерживается waitable
до TERM→KILL своей группы, чтобы исключить повторное использование PID в гонке
exit/descendant cleanup. Windows source/frozen execution требует реальной проверки
на Windows; документация Win32 и Linux-тесты не являются hardware qualification.

При PARSER_TIMEOUT, WRITER_TIMEOUT или RESOURCE_FAILURE финальный файл не
публикуется, следующий вход продолжается. CANCELLED остаётся отменой. Временные
raw и XLSX удаляются после завершения/ошибки; при последующем запуске помеченные
stale spools удаляются только с незанятым lease. Неизвестные и активные каталоги
не затрагиваются. Raw diagnostics по-прежнему opt-in. Принудительная остановка
процесса не обещает прерывания зависшего ядра ОС/файловой системы.

Salvage writer использует явный последовательный индекс строки. Лимиты до
выделения книги: 64 таблицы, суммарно 200000 структурных позиций, 100000 salvage
строк (также соблюдается Excel cap 1048576), 8 млн исходных символов; ответ
OCR — не более 4 млн символов. Длинные строки делятся по 32767 UTF-16 units.
Все наблюдения — text; исходные пробелы и порядок строк writer сохраняет, включая
явно переданные пустые строки. Parser по-прежнему отсекает пустые/control-only
строки. XML escape обратим после соединения split-строк: `\\` означает исходный
слеш, `\uXXXX` — недопустимый XML символ. Формулы не исполняются.

### Отказ doctor против отказа изображения

Каталог и journal ownership устанавливаются до doctor. Если начальная проверка
выбранного endpoint/token/model/engine не проходит, batch получает одну FAILED
запись с batch_level=true, stage=doctor, безопасным code, not_started/blocked и
инструкцией восстановления. summary/report сохраняются при доступном каталоге;
изображения не считаются попытками и XLSX не создаются. CLI exit3 сохранён.
Отдельный OCR/parser/writer отказ после успешной готовности — per-file FAILED;
очередь продолжается. Doctor OpenWebUI Chat остаётся мягкой проверкой видимости
model ID: успешный список не доказывает право на inference. Недоступность не
включает смену модели или server→Embedded fallback.

Summary отдельно содержит INPUT_TOTAL, UNIQUE_INPUTS (null, если не измерено),
ATTEMPTED (не resumed/skipped/batch), HTTP_ATTEMPTS (POST, включая retries),
FINISHED (завершённые новые SUCCESS/REVIEW/PARTIAL/FAILED), CANCELLED, SKIPPED,
RESUMED, FAILED и BLOCKED. BLOCKED при doctor — число не начатых файлов, FAILED
считает индивидуальные отказы; batch.status отражает отказ всего запуска.
XLSX_WITH_DATA, TABLE_STRUCTURED, PARTIAL_STRUCTURED и TEXT_SALVAGE_ONLY — разные
показатели; mixed structured+salvage не относится к text-only. NO_CONTENT и
DIAGNOSTIC_ONLY не дают data credit. Число непустых ячеек получено readback и
не является human-verified OCR accuracy. Исторические HG01/02/05 — calibration,
не unseen holdout. PARTIAL/REVIEW никогда не переводятся в SUCCESS.

`research.stage27` — отдельный finite qualification runner: protocol до inference,
serial GPU, локальный GLM с прежним digest/параметрами, mock и replay отдельно.
`scripts/stage27_windows/` — инструкции и smoke/build kit без release/bump/tag.
До реальной Windows frozen квалификации и приёмки PRODUCT_RELEASE=NO_GO.
