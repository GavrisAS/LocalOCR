# LocalOCR: независимый layout pilot, 23.10.2026

## A. Verdict

**Stage 1: NO_GO для production-интеграции проверенных маршрутов.** Независимая
геометрия Paddle существенно лучше baseline на новых synthetic inputs, но полный
Paddle OCR и региональный GLM не улучшили совокупное извлечение текста/структуры.
Первый кириллический pilot: baseline **123/171**, Paddle **78/171**, layout + GLM
**70/171** точных совпадений текста, логического индекса и span. На финальном hidden
holdout после freeze Paddle улучшил текст: **106/187 против 63/187** baseline
(layout+GLM 66/187). По двум новым наборам суммарно — **184/358 против 186/358**:
улучшение неоднородно и сопровождается примерно десятикратной стоимостью CPU pipeline. Это synthetic gold,
не независимая оценка точности на русских пользовательских сканах.

Geometry-only результат полезен: **71/171 → 153/171** на первом новом pilot и
**74/187 → 163/187** на финальном holdout сопоставленных cell polygons
при IoU≥0,5. Он не означает правильной связи текста с каждой геометрической ячейкой.
Production-ready backend не выбран. Stage 2 и Stage 3 не начаты; runtime, GUI,
CLI, Embedded, providers, `pyproject.toml`, `uv.lock` не изменены. Release/push/tag нет.
**Human gold: PENDING; реальная OCR quality: QUALITY_PENDING.**

Это ограниченный исследовательский pilot, а не выполненная квалификация универсального
OCR или тысяч изображений. NO_GO относится к проверенным конфигурациям, не ко всем
возможным вариантам Paddle/GLM.

## B. Git / branch / непушенные коммиты

На старте чистое дерево; HEAD = main =
`cbc71f1feb7679ab62faf6d935d8167c71648e9d`. `git fetch --no-tags origin main`
подтвердил origin/main `77e2aa349425bbea5d6c3014f48998cdc4be9710`.
Сохранены все семь исходных непушенных коммитов:

- `196e995` Record completed v0.29 Windows and Portable qualification
- `01ce0b1` Reconstruct tables with bounded spatial evidence and durable partial results
- `56c61e1` Compare serialized replay evidence and integral decimal formats accurately
- `7c1b3b5` Keep journal locks in the portable root and export bounded qualification evidence
- `d194606` Preserve pending quality and canonical settings when resuming GUI and CLI jobs
- `85343cb` Bound geometric hypotheses before allocating canonical cell evidence
- `cbc71f1` Document bounded table reconstruction qualification and quality limits

`src/` и прежние `tests/` между квалифицированным `85343cb282c70fe8d4838e386f74b10f4d170660`
и исходным HEAD совпадают. Новый source snapshot определяется `source_sha` в manifest
нового handoff; исследовательские файлы и тесты добавлены отдельным обычным коммитом.
История и старые теги не переписаны, version bump отсутствует. Финальный main остаётся
локальным; release gates не разрешают публикацию.

## C. Baseline / before / after

Проверен старый `.evidence/handoff-20261023/LocalOCR-handoff.zip`, SHA256
`8951d5f66ba75c44018aac8ccca20180bca08c1716fde76bc9ffdd31812a7f36`:
CRC и SHA256 всех members из manifest — PASS. Проверены исходные hashes **17/17**
в обоих прежних real runs. Под `data/layout-pilot-20261023/before/` сохранена
read-only копия **481** файла evidence; отдельный manifest фиксирует их SHA256.
Это защита от случайной перезаписи, не WORM-хранилище. Старый handoff не изменён.

Исторический полный run: 17 изображений, 208 POST / 1009,841 s, 16 PARTIAL + 1 REVIEW,
978 непустых наблюдений, 362 непривязанных, 3491 unresolved-позиций гипотезы,
0 human-verified anchors. Эти recorded results **не выдаются за новый live OCR**.
Прежний before: 74 POST / 556,631 s. Снижение FAILED не считается ростом accuracy.

Новый live baseline: прежние восемь fixtures, затем пять real inputs. Лимиты:
2 POST/image, retries=0, timeout=15 s, image budget=30 s. Производственный default
24 calls не увеличивался. Передача timeout в старый qualification runner ограничивает
запрос, но не гарантирует жёсткий image deadline: один baseline real input занял
30,959 s. Поэтому release-grade равенство временных бюджетов **не квалифицировано**.

Real pilot зафиксирован до новых ответов: прежние CASE-01,04,14,16,17 — тяжёлые
отказы, прежний технический SUCCESS, unplaced REVIEW и почти полная PARTIAL.
Private selection manifest содержит входы/hashes. Это стратификация по прежнему
поведению, **не независимо подтверждённая стратификация по типу layout**.
Полный новый 17-file holdout не запускался: ни один кандидат не прошёл выбор.

## D. Проверенные стратегии и identity

1. **Baseline:** неизменённая OpenCV line-grid/reconstruction + локальный GLM HTML.
2. **Candidate 1:** совместимый с PP-StructureV3 отдельный
   `TableRecognitionPipelineV2` из PaddleOCR 3.6.0 / PaddleX 3.6.1 / PaddlePaddle 3.3.0,
   CPU, четыре threads, MKLDNN off. PP-DocLayoutV3, wired/wireless SLANeXt,
   независимые RT-DETR cell detectors, PP-OCRv5 text detector, отдельный
   `cyrillic_PP-OCRv5_mobile_rec`, doc/table orientation. Это не весь PP-StructureV3
   с формулами/графиками и не продуктовый backend.
3. **Candidate 2:** PP-DocLayoutV3 table regions → GLM-OCR через существующий
   `OllamaClient`, без Torch/Transformers SDK, MaaS и облачного inference.
   Не более двух регионов; нет table region — нет выдуманной таблицы/fallback OCR.
   Table boxes не считаются cell boxes; HTML остаётся UNPLACED.

GLM во всех сравнениях: `glm-ocr:latest`, digest
`89d735dd9c07791953756edd275e5501464df61288b1cd5486c5c50c8c058b32`, F16;
Ollama **0.40.8**, runner `llamacpp`; `num_ctx=32768`, `num_predict=16000`,
`temperature=0`, `seed=0`, single-table `stop=['</table>']`, RGB/PNG.
Pull, замена/удаление модели, обновление Ollama, увеличение context не выполнялись.
Одинаковые параметры не гарантируют идентичные ответы: наблюдалась вариативность
между историческим и новым run. Из неё нельзя выводить улучшение алгоритма.

Paddle model revisions (полные file hashes и model-card licenses — model-manifest.json):

| Роль | Модель | Revision |
|---|---|---|
| Layout | PP-DocLayoutV3 | `241f8bdfc77a7c7bee915a5057aaee58c235a8d3` |
| Orientation | PP-LCNet_x1_0_doc_ori | `d3b95a6dff5fe8a94f2748e12b61cb26818a0df8` |
| Table class | PP-LCNet_x1_0_table_cls | `2fa6323e7dab88fa883081db1460995f46af2922` |
| Wired structure | SLANeXt_wired | `763069fcda6a065f2171753205a32bf899a88d15` |
| Wireless structure | SLANeXt_wireless | `1b73e05c752d2e0763b5d205846dec23122e5808` |
| Wired cells | RT-DETR-L_wired_table_cell_det | `e2bd53c06b3a815d86acbf5c6779dada58819cfe` |
| Wireless cells | RT-DETR-L_wireless_table_cell_det | `25ca86356a601c877476bb0dcc5fd09153d9d64d` |
| Text detector | PP-OCRv5_server_det | `ca867c897ecbca8873081573a802ad70d499cb94` |
| Text recognizer | cyrillic_PP-OCRv5_mobile_rec | `712d2d65556ccc1ea7b5d2bb232b018838b6a3ab` |

Model cards всех девяти weights указывают Apache-2.0; license metadata и SHA256
зафиксированы. Сумма локальных downloaded model files с README — **1 233 670 002 bytes**.
Список всех 97 research packages с точными версиями сохранён отдельно; это freeze
окружения, не Windows wheel lock с hashes и не изменение основного uv.lock.

## E. Численные результаты и границы метрик

Text metric требует совпадения row/column, текста и rowspan/colspan при совпавшем
размере единственной таблицы. Unresolved-пустоты не получают credit за пустой gold.
Индексы canonical/HTML **не означают подтверждённую исходную геометрию**.
`full_table_match` ниже — полное логическое совпадение, не human verification.

Прежние fixtures — регрессия, seeds 713093–713098 не использовались для настройки.
Baseline | layout+GLM | Paddle:

| Форма / угол | Gold anchors | Baseline | Layout+GLM | Paddle |
|---|---:|---:|---:|---:|
| Два grid controls, 0° | 18 | 18 | 18 | 18 |
| Broken, 2° | 38 | 31 | 37 | 0 |
| Grid, 90° | 40 | 32 | 31 | 25 |
| Open, −2° | 40 | 34 | 40 | 0 |
| Open, −2° | 34 | 22 | 29 | 0 |
| Borderless, 0° | 13 | 11 | 0 | 0 |
| Borderless, −2° | 20 | 14 | 0 | 0 |
| **Всего / полные логические таблицы** | **203** | **162 / 2** | **155 / 3** | **43 / 2** |

Для 90° baseline HTML содержит 32 совпадения, но наблюдения unplaced. Paddle cell
geometry дала **40/40** boxes IoU≥0,5; отдельно text/index/span — 25/40.
Ранее приведённые 167 baseline совпадений уменьшены до 162 после исключения пяти
unresolved-пустот. Это исправление scoring, не ухудшение live OCR.

Первый новый private seed сгенерирован до записи freeze manifest; inference на нём
начался после фиксации стратегии. Повторной настройки моделей/порогов не было.
Дополнительно сгенерирован отдельный финальный hidden seed строго после нового
freeze manifest и smoke; результаты обоих наборов сохранены, ни один не исключён. Новый generator:
кириллица, числа, пустоты, merged header, 0/90/180/270 и +2° skew. Seeds и synthetic
gold остаются в data. Восемь случаев не образуют полного factorial design:
layout type и orientation частично связаны; vertical/multilevel headers этим набором
не квалифицированы.

| Новый layout / угол | Gold | Baseline | Layout+GLM | Paddle | Boxes baseline / Paddle |
|---|---:|---:|---:|---:|---:|
| Grid 0° | 14 | 13 | 13 | 13 | 14 / 14 |
| Broken 90° | 27 | 26 | 0 | 22 | 0 / 27 |
| Borderless 180° | 24 | 0 | 0 | 2 | 0 / 13 |
| Open 270° | 15 | 14 | 14 | 15 | 0 / 15 |
| Grid 2° | 34 | 30 | 0 | 2 | 34 / 34 |
| Broken 92° | 14 | 11 | 11 | 4 | 0 / 14 |
| Borderless 182° | 19 | 15 | 10 | 18 | 0 / 12 |
| Open 272° | 24 | 14 | 22 | 2 | 23 / 24 |
| **Всего** | **171** | **123** | **70** | **78** | **71 / 153** |

Новый Paddle: 172 predicted boxes, 153 matched, 19 unmatched, 18 gold boxes missed.
Baseline: 73 hypothesis boxes, 71 matched, 2 unmatched, 100 missed. Matching:
one-to-one greedy по убыванию convex-polygon IoU, threshold 0,5; не row/span mapping.
Paddle shape совпала 8/8, baseline 7/8; полные логические text+span таблицы: 1/8 и 0/8.
Paddle box recall не легализует неверные spans/текст.

Position-conditioned CER/WER на новом synthetic: baseline **0,2128 / 0,2819**,
Paddle **0,6436 / 0,6242**. При неверной shape ожидаемые позиции считаются пропущенными;
это positional metric, не свободный reading-order CER. Отдельно считаются header
flags, spans, unresolved, unplaced, unsupported text occurrences в JSON matrices.
Unsupported occurrences — превышения multiset точных gold strings; OCR-ошибки тоже
попадают в этот показатель, поэтому это **не доказанный semantic hallucination rate**.
На real inputs CER/WER, accuracy, completeness, hallucination rate — **unknown/null**.

Финальный hidden holdout (после freeze, без последующей настройки):

| Layout / угол | Gold | Baseline | Layout+GLM | Paddle | Boxes baseline / Paddle |
|---|---:|---:|---:|---:|---:|
| Grid 0° | 14 | 11 | 11 | 14 | 14 / 14 |
| Broken 90° | 29 | 0 | 0 | 26 | 0 / 29 |
| Borderless 180° | 34 | 0 | 0 | 31 | 0 / 23 |
| Open 270° | 19 | 13 | 13 | 19 | 0 / 19 |
| Grid 2° | 14 | 14 | 0 | 4 | 14 / 14 |
| Broken 92° | 24 | 14 | 21 | 7 | 23 / 24 |
| Borderless 182° | 29 | 0 | 0 | 4 | 0 / 16 |
| Open 272° | 24 | 11 | 21 | 1 | 23 / 24 |
| **Всего** | **187** | **63** | **66** | **106** | **74 / 163** |

Paddle: 188 predicted boxes, 163 matched; baseline: 78 predicted, 74 matched.
Полные логические таблицы baseline/layout+GLM/Paddle: **1/0/2**; shape matches
baseline/Paddle **5/8 и 8/8**. CER/WER baseline **0,6042 / 0,6597**, Paddle
**0,5365 / 0,5486**. На этом конкретном holdout выигрыш текста и геометрии доказан;
он не отменяет регрессию первого нового pilot и двух реальных deadlines.
По двум новым наборам geometry matches **145/358 → 316/358**, text/index/span
**186/358 → 184/358**, полные логические таблицы **1/16 → 3/16**.
Это основание продолжать исследование geometry-only, а не считать полный Paddle OCR
универсально квалифицированным.


Пять real cases: baseline непустых observations 17/0/92/81/157; layout+GLM
0/0/105/0/134; Paddle 0/0/96/0/157 (два process deadlines). Это retention,
не числа правильных ячеек. Независимый human gold отсутствует во всех пяти.

## F. Latency / calls / resources / resume

| Pilot | GLM POST | Сумма s | p50 s | p95 s |
|---|---:|---:|---:|---:|
| Старые 8, baseline | 12 | 15,717 | 2,461 | 2,966 |
| Старые 8, layout+GLM | 6 | 29,659 | 4,072 | 5,444 |
| Старые 8, Paddle | 0 | 76,210 | 10,413 | 12,767 |
| Новые 8, baseline | 13 | 10,321 | 1,245 | 1,735 |
| Новые 8, layout+GLM | 7 | 52,694 | 6,385 | 8,544 |
| Новые 8, Paddle | 0 | 120,963 | 15,264 | 16,842 |
| Финальные 8, baseline | 14 | 11,935 | 1,329 | 2,916 |
| Финальные 8, layout+GLM | 8 | 49,992 | 6,288 | 6,588 |
| Финальные 8, Paddle | 0 | 126,584 | 15,841 | 17,193 |
| Real 5, baseline | 10 | 127,802 | 25,117 | 30,959 |
| Real 5, layout+GLM | 5 | 84,582 | 17,802 | 18,454 |
| Real 5, Paddle | 0 | 147,095 | 30,070 | 30,080 |

Paddle 0 POST означает отсутствие GLM; native detector/recognizer forward counts
не инструментированы. Candidate 1 использует CPU, GLM — GPU; это не hardware-normalized
speed test. Новые Paddle и DocLayout выполнены с cold per-image subprocess deadline
30 s, включая initialization; старые Paddle eight timings исключают 3,061 s общей
initialization. Layout+GLM new включает cold detector costs. Baseline использует уже
загруженный Ollama. Некоторое QA выполнялось на том же хосте. **Эти ограничения не
позволяют release-grade latency A/B; оснований заявлять отсутствие регрессии нет.**
Real Paddle: 3 processed, 2 DEADLINE_EXCEEDED; pre-bounded проба >30 s остановлена
и не подменяет bounded results. Все partial process artifacts и диагностика остаются
под data; исследовательские кандидаты не публикуют XLSX.

120 system-wide samples с интервалом 2 s (sampler запущен после начала pilot):
max research-worker RSS **5 466 066 944 bytes**, system CPU 3–67%, system GPU peak
62%, system GPU memory max **9227 MiB**. Это shared-host snapshots, **не attributed
GLM/Paddle peaks** и не strict full GPU offload proof. Хост: Linux, RTX A4000 16 GB;
Paddle CPU. Полная процессная/VRAM трассировка всего baseline не выполнена.

Throughput на тысячах, p95 устойчивого потока и resume-after-failure **NOT_QUALIFIED**.
Старое cache/resume evidence не объявляется новым экспериментом. Production fingerprint
по-прежнему не содержит server/runner build identity; при его смене нужен явный
`overwrite`. Новый requalification epoch/flag описан архитектурно, не внедрён без Stage 1
PASS. Неизменный digest не объявляется достаточным для эквивалентности cache.

## G. Source / evidence audit / проверки

Raw OCR, изображения, crops, synthetic gold, real selection hashes, human template,
локальные weights, process logs находятся только в `data/layout-pilot-20261023/`.
`/data/` остаётся ignored; `git ls-files data` пуст. В трёх старых engineering audits обезличены ссылки с именами приватных файлов; исторические коммиты не переписаны. В handoff попадают только
allowlisted anonymized matrices, model manifests, package freeze, JUnit, отчёт и source.
Никакой OCR ответ не записан в human gold.

Human template: `data/layout-pilot-20261023/human-gold/index.html` и `template.json`.
Страница показывает пять изображений и инструкцию ручной разметки original pixels,
rows/columns/spans/headers/text; значения отсутствуют. Только человек может установить
human_verified после проверки. Шаблон с приватными references в handoff не включён.

Ruff check, Ruff format --check, ty — PASS. Финальный pytest: **327 passed**, включая
прежние 318 и 9 тестов scoring (inverse rotations/skew, polygon IoU, Cyrillic edit
metric, запрет credit unresolved-пустоте). JUnit — `regression.xml`. Это software
regression/scoring validation, не гарантия OCR accuracy. Ни recorded replay, ни mock
не учитываются как live inference в приведённых pilot matrices.

Официальные источники:

- [PaddleOCR PP-StructureV3](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/PP-StructureV3.en.md)
- [TableRecognitionPipelineV2 API](https://github.com/PaddlePaddle/PaddleOCR/blob/main/paddleocr/_pipelines/table_recognition_v2.py)
- [PP-DocLayoutV3 weights/model card](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3)
- [GLM-OCR SDK](https://github.com/zai-org/GLM-OCR)

Mutable documentation не используется как weight identity: конкретные revisions/files
зафиксированы manifest, effective Paddle config сохранён приватно.

## H. Portability / offline gate

Основной проект: Python 3.14.8, committed uv.lock. Research: отдельная Python 3.12.15
venv под data; 97 packages. Поддержка Python 3.14/Windows у этой сборки Paddle
**не проверена**. Windows frozen / GPU bundles **NOT_RUN / NOT_ADDED**; существующий
Lite не изменён. Как минимум 1,234 GB weights плюс Paddle/native runtimes, venv и
лицензионные notices потребуются отдельному flavor; итоговый Windows размер неизвестен.

Fetch weights — явная development-команда. Inference получает только model_dir,
проверяет hashes, выставляет HF offline и запрещает Python socket connect.
Запрет поймал скрытый orientation auto-download; локальный config исправлен, после
этого complete runs работают с local weights. Это не OS-level firewall/native egress
audit: production offline gate остаётся **PENDING**. Тяжёлые research deps в
pyproject/uv.lock не добавлены; исходный GLM SDK в продукт не подключён.

## I. Известные ограничения

Нет production Alignment/independent text-box integration, альтернатив сетки,
квалифицированных multilevel/vertical headers и универсального borderless path.
PP-DocLayout page regions и unordered cell detections не подтверждают HTML cell order.
Paddle postprocessing может группировать boxes по ожидаемому HTML cell count;
необходимо сохранять это provenance и ambiguity, а не принимать за независимый gold.
Специализированный Cyrillic recognizer не квалифицирован для Latin-heavy старых fixtures.

Контракт `TableRegion → OrientationCandidate → CellGeometry → TextBox/Observation →
Alignment → CanonicalTable` и раздельные structural completeness / content evidence /
human_verified изложены в `research/ARCHITECTURE.md`. Это проект следующего этапа,
не заявление о выполнении Work Package C. Название production unplaced sheet, новая
cache invalidation, статусы и backend integration в этом NO_GO не изменялись.

## J. Рекомендация / воспроизведение / handoff

**NO_GO Stage 2:** не включать проверенные pipelines в Portable и не увеличивать
max_calls/context. Для нового исследования перспективен geometry-only Paddle +
тот же GLM с настоящим TextBox→Cell matching, orientation hypotheses и ambiguity;
это ещё не проверенный кандидат. До такого решения нужны human annotations,
независимый новый factorial holdout и измеренный экономный routing. Stage 3 и Windows
qualification следуют только после выбранного PASS-кандидата.

Проверенные команды (рабочий каталог — repo; новые output directories обязательны):

```bash
uv venv --python 3.12 data/layout-pilot-20261023/venv
uv pip install --python data/layout-pilot-20261023/venv/bin/python paddleocr==3.6.0 paddlepaddle==3.3.0 'paddlex[ocr]==3.6.1'
uv run python research/layout_pilot.py fetch --weights data/layout-pilot-20261023/weights --manifest .evidence/layout-pilot-20261023/public/model-manifest.json
uv run python scripts/qualify_tables.py data/hybrid-holdout --output data/reproduce-baseline --calls 2 --seconds 30 --timeout 15
uv run python research/run_bounded.py table --python data/layout-pilot-20261023/venv/bin/python --weights data/layout-pilot-20261023/weights --input data/layout-pilot-20261023/new-holdout-frozen --output data/reproduce-paddle
uv run python research/score_paddle.py data/reproduce-paddle --gold data/layout-pilot-20261023/new-holdout-frozen/gold.json --output data/reproduce-score
uv run python research/run_bounded.py layout --python data/layout-pilot-20261023/venv/bin/python --weights data/layout-pilot-20261023/weights --input data/layout-pilot-20261023/new-holdout-frozen --output data/reproduce-layout
uv run python research/regional_glm.py data/reproduce-layout --output data/reproduce-regional
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

Для точной среды использовать handoff `research-requirements.txt`; для exact weights
нужны revisions/hashes manifest, а не новое mutable main. Fetch откажет при изменившемся
revision в уже закреплённой директории; новый upstream revision — отдельная квалификация.
Synthetic inputs воспроизводятся `research/new_holdout.py --seed` из приватного gold;
новый seed без аргумента — новый эксперимент, не replay прежнего.

Новый handoff: `.evidence/layout-pilot-20261023/handoff/LocalOCR-layout-pilot-handoff.zip`.
Source — exact git archive SHA manifest, `uv.lock` внутри source.zip. Веса, документы,
изображения, raw OCR, XLSX, конфигурации/токены и process logs исключены. Utility
проверяет CRC обоих ZIP, member SHA256 и запрещённые пути; SHA256SUMS и итоговый checksum
лежат рядом. Архив <100 MB; при превышении utility делит на тома 100000000 bytes.
