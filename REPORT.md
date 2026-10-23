# LocalOCR — REPORT (23.10.2026)

## A. Вердикт

**Общий результат: PARTIAL.** Локальная инженерная квалификация — **PASS**;
software/release qualification целиком — **PARTIAL**, поскольку новый SHA не проходил
Windows/CI/Embedded hardware. OCR quality — **QUALITY_PENDING**, а gate полного
восстановления новых сложных synthetic таблиц — **FAIL: 0/6**.

На одном и том же новом digest выполнены before/after всех **17/17 файлов**
(16 уникальных source hashes). Before: 15 FAILED, 1 прежний SUCCESS, 1 REVIEW.
After: **16 PARTIAL, 1 REVIEW, 0 SUCCESS, 0 FAILED**. Это 17 непустых проверяемых XLSX,
**не 17 достоверно распознанных таблиц**. Сохранено 978 непустых OCR-наблюдений:
616 с поддержкой координатной геометрии, 362 с явно непроверенной привязкой.
**Подтверждённых по human gold anchors: 0.** Количество наблюдений не является
долей правильно распознанных исходных ячеек.

Прогресс — сохранение применимых частей и прозрачное описание неизвестного;
улучшение истинной OCR accuracy без human gold не доказано. Полный автоматический
общий случай не решён. Релиз не опубликован, push не выполнен.

## B. Git/version и сохранность

- На старте: чистое tracked/untracked рабочее дерево; локальный HEAD
  `196e9955384fe9052d8134f9c4c72451558a8170`, на один documentation-only commit впереди main.
- Проверенные origin/main и immutable tag `v0.29`:
  `77e2aa349425bbea5d6c3014f48998cdc4be9710`.
- SHA квалифицированного software: **`85343cb282c70fe8d4838e386f74b10f4d170660`**.
- Исходный локальный commit `196e995` сохранён в истории. Для before использован
  его отдельный `git archive`; runtime-код идентичен публичному `77e2aa3`.
- Последующий documentation-only commit с этим отчётом указан как `source_sha` в
  handoff `manifest.json`; его `src/` и `tests/` совпадают с квалифицированным SHA.
- Force push, переписывания истории, version bump commits и новых тегов нет.
  Следующий main push потребует очередной MAJOR.MINOR reservation; сейчас gates
  не разрешают выпуск. Старые релизные assets не изменялись.
- `/data/` в `.gitignore` сохранён. У всех before/after входов совпали SHA256,
  проверки неизменности исходников изображений — 17/17 в каждом прогоне.
  Пользовательские изображения, тексты OCR, XLSX, raw diagnostics и веса в Git,
  CI, release и handoff не включены.

## C. Ollama и контроль параметров

Фактически использован **Ollama Direct `http://127.0.0.1:11434/api/generate`**.
CLI и `/api/version`: **0.40.8**. Portable `config.json` отсутствовал; прочитанная
без изменения legacy-конфигурация выбирает этот Direct backend для full GUI/CLI.
Простой режим «Сервер» использует OpenWebUI Proxy `127.0.0.1:8080`; токен не задан,
диагностические API не прошли. **Digest proxy не проверен — PENDING_PROXY**;
локальный digest на него не переносится.

`glm-ocr:latest` уже был обновлён на старте задания:
`89d735dd9c07791953756edd275e5501464df61288b1cd5486c5c50c8c058b32`.
API сообщает F16, glm4, 891.14M + vision projector, model context 131072.
Template в `/api/show`: `{{ .Prompt }}`; model parameter `temperature 0`.
[Публичный tag](https://ollama.com/library/glm-ocr:latest) совпадает по короткому digest.

Реальные before/after параметры: `temperature=0`, `seed=0`, `num_ctx=32768`,
`num_predict=16000`, single-table `stop=['</table>']`; page/text calls без этого stop.
RGB/PNG без общего downscale; реальные crop boxes/размеры и usage остаются в
приватных machine-readable manifests. В квалификации timeout запроса 60 s,
24 попытки/180 s на изображение, retries=0, один worker. Runtime default timeout
300 s; общий лимит 180 s для Direct/Proxy, 600 s для Embedded CPU/GPU;
транспортные retries входят в общий физический лимит 24 попытки.

`/api/ps` подтвердил runner `llamacpp`, context 32768 и `size_vram=3966144347` байт.
Это snapshot API, **не peak NVML и не strict Embedded GPU proof**. Хост — Linux,
RTX A4000 16 GB; Windows hardware этим не квалифицирован.

Старый digest из отчёта —
`6effedd0dc8aec66ad86c94b8099395376e212f22c87a9d7147c422f7e447be4`.
Старый tag/manifest не обнаружен. Чистое old/new A/B — **PENDING_MODEL**;
исторический запуск Ollama 0.40.7 нельзя смешивать с этим A/B. Pull, удаление моделей,
новые aliases и изменения Portable GGUF/llama.cpp не выполнялись.

Короткий benchmark — **18 POST**: два сложных real input, два synthetic control,
8K/16K, stop/no-stop, generate/chat, resize 75%, JPEG95 и один замкнутый ROI
Text/Table. На обоих контролях generate дал 9/9, chat отдельно проверен на 9/9.
Два сложных входа остались непарсируемыми во всех проверенных вариантах;
real text coverage без gold = null. 8K/16K не увеличили извлечённую структуру;
максимум наблюдаемого prompt+output в benchmark — 7140 токенов. Оснований для
64K/128K context либо увеличения generation нет. 75% resize/JPEG не дали
структурного исправления. Размер букв внутри vision encoder не измерен.
**Сохранены generate, 32768/16000, stop и полный RGB/PNG.**

В benchmark все 18 запросов завершились stop, возвращённые thinking-поля пусты;
это не проверка внутреннего rendered prompt/token IDs. В полном after всё же
зафиксированы **2 HTTP 500 TOKEN_REPEAT_LIMIT и 5 timeout**. У 201 завершённого
ответа — stop, у 7 ошибочных причина остановки неизвестна. Симптом повторов остаётся;
его точное совпадение с legacy EOT-причиной не доказано. Контекст не объявляется
лекарством. [Issue 18609](https://github.com/ollama/ollama/issues/18609) и
[issue 18810](https://github.com/ollama/ollama/issues/18810) описывают связанные
legacy EOT/template/thinking дефекты; локальные версии и новые crops требуют
отдельного подтверждения. Текущий dev digest оставлен; в Portable он не перенесён.

## D. Причины и реализация

| Этап | Наблюдение и решение |
|---|---|
| Model generation | Правильный stop сопровождается потерей td/строк и неверными spans; новые crops также вызывают repeat limit. HTML не подтверждает полноту или accuracy. |
| Image preprocessing | RGB/PNG и исходное разрешение сохранены; EXIF/deskew имеют обратное преобразование. Произвольный поворот 90° не решён. |
| Geometry | Отдельный GridHypothesis: поддержка сегментов границ и проверка половинного масштаба. Отсутствие линии не создаёт merge. Большие гипотезы ограничены до выделения матриц: 10000 rows, 1000 columns, 100000 slots. Линии остаются гипотезой, text-column detector пока отсутствует. |
| Parser | Строгая rectangular/span validation сохранена. Закрытые наблюдения повреждённых строк отделены от canonical grid; применимая строка привязывается только при доказуемой ширине и позиции. |
| Assembly | Применимые anchors переживают сбой соседней строки/merge. Разрезы только по безопасным границам; нет удаления реальных строк по равному тексту. Без геометрии сохраняются отдельные непривязанные наблюдения, а не выдуманная общая сетка. |
| Output | Валидированный canonical document, атомарный XLSX, inert strings, отсутствие comments. `Проверка`: 1-based row/column, reason, normalized ROI и полигон оригинала. |

В after зафиксированы 43 ragged-grid parser rejection, 15 span-outside,
20 no-table response, 57 geometry shape disagreement, 4 прочих отказа validation,
2 repeat limit и 5 timeout. Эти счётчики описывают запросы/валидации и могут относиться
к одному изображению; их нельзя складывать в число ошибочных файлов. Ошибка parser
здесь часто является обнаружением ошибки генерации, а не доказательством бага parser.

`TextObservation` и `CellProvenance` содержат факты и source coords, без выдуманной
модельной вероятности. Исключительные Text Recognition ROI ограничены тремя на
таблицу и общим бюджетом. Полноценный независимый text/layout path, ensemble структур,
header context pass и разрешение всех безрамочных/вертикальных заголовков **не завершены**.

Журнал `results/jobs.jsonl`: source path/hash, digest/backend, settings_hash,
pipeline version, attempts, status/output hash/latency. OS locks живут в portable
root `work/journal-locks/`, JSON reports атомарны. Смена модели/настроек инвалидирует
ключ; старые книги сохраняются. Известный digest обязателен для cache hit.
GUI/CLI численно равные timeout дают один fingerprint. Cache сохраняет REVIEW/PARTIAL,
anchors и unresolved/unverified, отмечает resumed и нулевые новые calls;
повторный CLI сохраняет exit 1 для ожидающей проверки работы. Проверено на восьми
реальных synthetic job outputs: 8/8 cache hit, 0 новых OCR, 4 REVIEW + 4 PARTIAL.
Один файл/сбой сервера не превращается в бесконечный crop retry; отмена блокирует
публикацию временной книги. Backend version при неизменном Ollama digest отдельно
в ключ не входит; после такого обновления для повторной квалификации нужен overwrite.

## E. Sanitized матрица 17/17

Во всех строках verified content anchors = **0**. `Непустые / геометрия` — количество
наблюдений и подмножество с поддержанными границами, **не verified OCR**.
`Unresolved` — позиции в гипотезе, а не истинное число пропущенных исходных ячеек;
при непривязанном OCR оно неизвестно. Истинное покрытие без gold неизвестно везде.
Предыдущий SUCCESS означает только прежний технический outcome.

| CASE | Before | After | Непустые / геометрия | Unresolved | POST | s | Основные причины |
|---|---|---|---:|---:|---:|---:|---|
| CASE-01 | FAILED | PARTIAL | 36 / 36 | 350 | 17 | 63.595 | PARSER_RAGGED_GRID, GRID_SHAPE_DISAGREEMENT |
| CASE-02 | FAILED | PARTIAL | 30 / 0 | неизв. | 4 | 29.435 | NO_TABLE_RESPONSE, OTHER_VALIDATION |
| CASE-03 | FAILED | PARTIAL | 78 / 0 | неизв. | 4 | 51.614 | PARSER_RAGGED_GRID |
| CASE-04 | FAILED | PARTIAL | 52 / 52 | 526 | 13 | 75.585 | PARSER_RAGGED_GRID, PARSER_SPAN_OUTSIDE |
| CASE-05 | FAILED | PARTIAL | 18 / 18 | 283 | 15 | 49.511 | PARSER_SPAN_OUTSIDE, PARSER_RAGGED_GRID |
| CASE-06 | FAILED | PARTIAL | 23 / 23 | 297 | 20 | 55.289 | GRID_SHAPE_DISAGREEMENT, PARSER_RAGGED_GRID |
| CASE-07 | FAILED | PARTIAL | 27 / 27 | 309 | 10 | 40.908 | PARSER_RAGGED_GRID, TOKEN_REPEAT_LIMIT |
| CASE-08 | FAILED | PARTIAL | 27 / 27 | 309 | 10 | 31.052 | PARSER_RAGGED_GRID, TOKEN_REPEAT_LIMIT |
| CASE-09 | FAILED | PARTIAL | 28 / 28 | 322 | 11 | 101.474 | PARSER_SPAN_OUTSIDE, PARSER_RAGGED_GRID |
| CASE-10 | FAILED | PARTIAL | 21 / 21 | 340 | 7 | 22.674 | PARSER_RAGGED_GRID, PARSER_SPAN_OUTSIDE |
| CASE-11 | FAILED | PARTIAL | 90 / 90 | 68 | 15 | 157.293 | PARSER_RAGGED_GRID, GRID_SHAPE_DISAGREEMENT |
| CASE-12 | FAILED | PARTIAL | 29 / 29 | 429 | 24 | 69.702 | GRID_SHAPE_DISAGREEMENT, PARSER_RAGGED_GRID |
| CASE-13 | FAILED | PARTIAL | 3 / 3 | 133 | 12 | 75.127 | NO_TABLE_RESPONSE, GRID_SHAPE_DISAGREEMENT |
| CASE-14 | SUCCESS | PARTIAL | 94 / 94 | 123 | 24 | 99.015 | GRID_SHAPE_DISAGREEMENT, NO_TABLE_RESPONSE |
| CASE-15 | FAILED | PARTIAL | 45 / 0 | неизв. | 4 | 28.464 | NO_TABLE_RESPONSE, PARSER_RAGGED_GRID |
| CASE-16 | FAILED | REVIEW | 209 / 0 | неизв. | 1 | 20.109 | UNPLACED_OBSERVATION |
| CASE-17 | REVIEW | PARTIAL | 168 / 168 | 2 | 17 | 38.994 | GRID_SHAPE_DISAGREEMENT, NO_TABLE_RESPONSE |

Всего: 978 непустых, 616 с геометрией, 362 непривязанных; **3491 явно unresolved slot**
в геометрических гипотезах. Никаких заполнителей как реальных значений нет.
Физически пустая unresolved Excel-позиция отличается состоянием, цветом и записью
`Проверка` от наблюдения пустой исходной ячейки. Исходные изображения и точные
source hashes/coords/ответы доступны только локально в `data/hybrid-*`.

Контроли из before не скрыты: CASE-14 — 105 → 94 непустых наблюдения и
15.191 → 99.015 s; CASE-17 — 166 → 168 и 20.142 → 38.994 s. Это ограничение/регрессия
retention и стоимости на первом контроле, требующая независимого gold и другой
структурной гипотезы. Оснований объявлять улучшение каждого файла нет.

## F. Generalization и performance gates

Независимый seeded generator: random rows/columns, пустые ячейки, горизонтальные и
вертикальные spans, размеры шрифта, разрывы/отсутствие рамки, вертикальный текст,
повороты; 40 seeds дополнительно проверены без модели. Искусственные пропуски
OCR/td/row/span проверяются отдельно. Пороги/ветки по именам, текстам или размерам
17 исходников отсутствуют. Для holdout алгоритм не перенастраивался.

Два простых контроля и шесть новых форм, seed 713091…713098:

| № | Форма | Поворот | Совпало anchors / gold | Полный text+position+span match |
|---|---|---:|---:|---|
| 1 | grid | 0° | 9/9 | PASS |
| 2 | grid | 0° | 9/9 | PASS |
| 3 | broken | 2° | 32/38 | QUALITY_PENDING |
| 4 | grid | 90° | 0/40 | QUALITY_PENDING |
| 5 | open | -2° | 35/40 | QUALITY_PENDING |
| 6 | open | -2° | 25/34 | QUALITY_PENDING |
| 7 | borderless | 0° | 11/13 | QUALITY_PENDING |
| 8 | borderless | -2° | 14/20 | QUALITY_PENDING |

Итого 135/203 anchors с точным совпадением (включая пустые и spans).
Простые контроли: 18/18 и 2/2 полных совпадения. Шесть новых форм: 117/185,
**0/6 полных совпадений**. У 90° — 0/40. У одного borderless input совпал весь
непустой текст, но полного совпадения пустых/merged позиций нет. Это небольшой
Latin/digit holdout; он не квалифицирует точность русских сканов или произвольных
документов. Runtime честно оставил 4 REVIEW и 4 PARTIAL.

| Живой прогон | POST | Сумма s | Median s/file | p95 s/file |
|---|---:|---:|---:|---:|
| Before, 17 | 74 | 556.631 | 26.625 | 132.766 |
| After, 17 | 208 | 1009.841 | 51.614 | 157.293 |
| Последний synthetic, 8 | 42 | 30.103 | 4.0235 | 6.845 |

p95 — nearest rank; на 17 входах это максимум. Это реальные wall timings,
не extrapolation. Хост одновременно выполнял локальный QA; испытание не является
изолированным многократным throughput benchmark. After дороже: 208 против 74 calls,
производительность на тысячи файлов **не квалифицирована**. Есть контроль бюджета,
журнал и один worker, но нет измеренного прогона 1000 файлов или VRAM peak.

В after API сообщил 101678 output tokens для 201 completed response; у 7 ошибочных
usage недоступен, так что это нижняя граница фактической генерации. У before usage
не был записан — нулевые значения не выдаются за измерение. Layout/OCR/total timings
для 17 и load/encode/provider/parse/reconstruction/write timings последних synthetic
сохранены отдельно. Recorded replay не участвует в live latency.

**Следующий архитектурный шаг:** независимые text/line boxes и orientation/layout
candidate, геометрическое согласование наблюдений и отдельный header pass.
[Официальный SDK](https://github.com/zai-org/GLM-OCR) с PP-DocLayoutV3 рассмотрен
статически: [selfhosted deps](https://github.com/zai-org/GLM-OCR/blob/main/pyproject.toml)
включают Torch/torchvision/Transformers; проверенный
[config](https://github.com/zai-org/GLM-OCR/blob/main/glmocr/config.yaml) включает MaaS,
Hub model ID и 32 workers. Для LocalOCR нужны pinned local weights/commit,
запрет сети и один worker в отдельном owned runtime. SDK не установлен и не объявлен
offline-qualified; Python 3.14/Windows compatibility не проверена. В Portable он
не включён. Повторный бесконтрольный перебор CASE-01 не проводился.

## G. Регрессия и CI evidence

Код **`85343cb282c70fe8d4838e386f74b10f4d170660`**, Python 3.14.8, committed uv.lock.
`uv sync --locked`, Ruff check/format, ty — PASS. **318 pytest, 0 failures,
0 errors, 0 skipped**, JUnit `regression.xml`, SHA256:
`d828ee93aa74c428e7fcaf2b7d110ff6d7adea668c00a0b06c3d9039a910ff66`.

На том же software SHA собраны Linux frozen CLI и GUI. CLI Unicode/image→HTTP mock→XLSX
roundtrip — PASS. Simple и Full GUI из другого CWD с profile traps — PASS;
фактический build commit проверен. Это GUI/CLI software smoke, не OCR hardware proof.
API/backend, TLS/proxy/redirect, Auto/GPU/CPU, cancellation и portable-root regressions
проверены pytest на synthetic/mocks. Live Embedded на этом хосте — PENDING_NO_ENGINE;
live OpenWebUI — PENDING_PROXY. **Windows frozen/new CI — PENDING_NOT_RUN**.

По публичному `77e2aa3` повторно проверены успешные
[CI](https://github.com/GavrisAS/LocalOCR/actions/runs/39756985199) и
[Windows candidate](https://github.com/GavrisAS/LocalOCR/actions/runs/39756985133).
Они относятся к v0.29 и не переносятся на новый SHA. GPU packaged, Linux hardware
qualified и Windows hardware qualified остаются разными состояниями. Новых CI jobs,
release или tags в этой сессии нет.

Финальный recorded replay — **17/17 одинаковых canonical outcomes** на сохранённых
ответах, без новых model calls; он связывает live recovery с финальными safety/cache/
reporting изменениями. Отдельно открыты реальные XLSX: values, data_type,
number_format, spans, comments и formula safety; проверены 4950 canonical anchors
финальных 17 книг и все 8 synthetic outputs. Это Excel fidelity, не проверка OCR
по изображению. Авторазмеры ограничены 8–52 units / 150 pt; переполнение отображения
имеет DISPLAY_LIMIT, значения сохраняются.

## H. Handoff и воспроизведение

Отчёт: `REPORT.md`. Handoff: `.evidence/handoff-20261023/LocalOCR-handoff.zip`;
checksum `.zip.sha256` и `SHA256SUMS`, точный source HEAD — `manifest.json`.
Архив содержит source/docs и allowlisted sanitized evidence/JUnit/CI, без data,
raw OCR, имён исходных изображений, XLSX, логов, конфигураций и весов. Проверяются
чтение/CRC обоих ZIP и SHA256 каждого member. Итоговый SHA256 также приведён в
финальном сообщении; он хранится вне содержащего REPORT архива. Размер меньше
100 MB; тома не нужны. При большем размере utility создаёт части по 100000000 bytes
и инструкцию JOIN.txt.

Минимальная проверка на текущем хосте:

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest --junitxml=.evidence/hybrid/regression.xml
uv run python scripts/qualify_tables.py data --output data/reproduce-after
uv run python scripts/benchmark_ollama.py data --output data/reproduce-parameters
uv run python scripts/generate_holdout.py --output data/reproduce-holdout --seed 713091 --count 8
uv run python scripts/qualify_tables.py data/reproduce-holdout --output data/reproduce-holdout-run --through-service
uv run python scripts/replay_tables.py data/hybrid-after --output data/reproduce-replay
uv run python scripts/check_workbooks.py data/reproduce-replay --output .evidence/reproduce-excel.json
(cd .evidence/handoff-20261023 && sha256sum -c LocalOCR-handoff.zip.sha256)
```

Для before: распаковать `git archive 196e995` в отдельный каталог и передать его
`qualify_tables.py --source-root`; входы/модель/параметры оставить прежними. Все
output directories должны быть новыми. Полные manifests и source mapping лежат
локально в `data/hybrid-baseline`, `data/hybrid-after`, `data/hybrid-parameters`,
`data/hybrid-holdout-final`, `data/hybrid-final-code-replay`; они не являются handoff.
Для повторного OCR готовых cached outputs нужен `--overwrite`; cached pending
качество не превращается в SUCCESS. Новая публикация допустима только после
закрытия OCR/gold, performance и Windows gates. **Production ready не объявляется.**
