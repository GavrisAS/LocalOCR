# Evidence-based восстановление (локальный candidate)

Общий сервис GUI/CLI использует `reconstruction.py`. Геометрия, HTML и текст ROI —
разные наблюдения. Константа `PIPELINE_VERSION` входит в ключ возобновления.
Смена алгоритма должна менять эту константу; теги релиза по-прежнему MAJOR.MINOR.

## Данные и статусы

`GridHypothesis` хранит поддержку каждого сегмента границы и согласие с детекцией
в половинном масштабе. Отсутствие линии само по себе не создаёт merge. Для span нужны
OCR-span, четыре внешние стороны и отсутствие поддержанной внутренней линии.
При открытой рамке гипотеза может оставаться неполной: геометрия не является gold.

`TextObservation` связывает ответ с точным ROI и запросом. `CellProvenance` хранит
наблюдаемые факты, состояние и полигон в координатах оригинала. `source_region` —
прямоугольник нормализованного изображения; EXIF и deskew имеют обратное affine
преобразование. RGB/PNG сохраняет разрешение; автоматического downscale нет.

Успешный HTML ещё не подтверждает OCR-текст. Статусы результата:

- `SUCCESS`: есть непустые anchors, нет unresolved/unverified и предупреждений.
  Текущий автоматический маршрут не назначает `corroborated` одному OCR-ответу,
  поэтому его обычный полный результат — `REVIEW`, а не утверждение точности.
- `REVIEW`: применимая canonical таблица или явно непривязанное OCR-наблюдение;
  содержание/геометрия требуют сверки. Это не human-gold PASS.
- `PARTIAL`: сохранены непустые наблюдения и известны нерешённые позиции/регионы.
  Пустая Excel-позиция с `provenance.state=unresolved` не считается пустой исходной
  ячейкой или распознанным значением. Она окрашена и описана в `Проверка`.
- `FAILED`: непустых структурно применимых наблюдений нет; XLSX не публикуется.
- `SKIPPED`: файл существует или подтверждено возобновление; это не новый OCR PASS.

`recognized_anchors` считает непустые OCR-наблюдения, включая явно непривязанные;
`verified_anchors` — только corroborated. Это разные величины.
`unverified_content` — непустые anchors без подтверждения.
`unresolved_anchors` — конкретные неразрешённые позиции canonical сетки.
`unresolved_regions` — число unresolved-позиций плюс записи нерешённых областей
документа (не число уникальных исходных ячеек и не площадь; области могут перекрываться).

## Восстановление и границы применимости

Сначала используются целые таблицы или неперекрывающиеся группы строк по безопасным
геометрическим границам. При ошибке сохраняются применимые anchors, а меньшие группы
получают ограниченные повторные запросы. Закрытые строки повреждённого HTML можно
привязать лишь при точном совпадении числа исходных строк и полной ширине данной
строки, без влияющего rowspan. Пропущенный непустой ряд не заменяется пустым.

Видимые отметки после удаления длинных линий служат сигналом неполноты, а не OCR
или вероятностью. Пустой ответ поверх таких отметок оставляет unresolved.
Исключительный бюджет до трёх `Text Recognition:` ROI на таблицу применяется только
к отдельно замкнутым ячейкам и укладывается в общий бюджет изображения. Обычный
маршрут не вызывает LLM для каждой ячейки. Chat/Embedded продолжают прежний table API.

Без линий HTML остаётся непривязанным наблюдением; фрагменты не склеиваются по
совпадающим строкам. Сохраняются отдельные листы/регионы, включая повторяющийся текст.
Закрытые прямоугольные серии строк из повреждённого ответа тоже являются только
непривязанными наблюдениями. Неизвестные merges не объявляются доказанными.
Полноценного независимого детектора текстовых колонок пока нет. Устойчивость ко всем
поворотам, фотографии и разорванным линиям не квалифицирована.

Writer сохраняет только validated canonical таблицы. OCR-строки не становятся
формулами. `Проверка` содержит 1-based row/column, reason и ROI; comments отсутствуют.
Авторазмеры: ширина 8–52 Excel units, высота до 150 pt, текст переносится; превышение
даёт `DISPLAY_LIMIT`. Это ограничения отображения, не обрезание значений.

## Бюджет и возобновление

Начальный режим — один worker. По умолчанию 24 физических HTTP OCR-попытки и
180 s на распознавание изображения Direct/Proxy и 600 s для Embedded (запас для CPU); timeout одного запроса 300 s ограничивается
остатком общего времени. Предобработка/запись измеряются отдельно и в этот лимит
генерации не входят. При исчерпании бюджета публикуется только законченная partial
книга с явными unresolved либо `FAILED`. Нет повторного детерминированного запроса
после `TOKEN_REPEAT_LIMIT`. Отмена до публикации удаляет временный XLSX.

В `results/jobs.jsonl` находятся source path/hash, backend/model identity,
settings/pipeline, attempts, status, output hash и latency. Записи fsync; оборванная
запись игнорируется. OS lock допускает один writer данного каталога и снимается
после падения процесса. XLSX и JSON reports публикуются атомарно.

Завершённые `SUCCESS/REVIEW/PARTIAL` с известным digest и совпавшими хешами можно
возобновлять без OCR; `PARTIAL` остаётся partial, а не превращается в success.
Изменение входа/настроек/digest создаёт другой ключ и другое имя XLSX, сохраняя
прежнюю книгу. Неизвестный digest (например ограниченный OpenWebUI Chat) запрещает
автоматический cache hit. Существующий файл без подтверждённого fingerprint требует
`--overwrite`; он не считается результатом новой модели. `--overwrite` также повторяет
partial OCR. API-токен исключён из журнала; user config по-прежнему plain JSON.

Expert JSON, не дополнительные поля простого GUI:
`ollama_num_ctx=32768`, `ollama_num_predict=16000`, `ollama_table_stop=true`,
`ocr_max_calls=24`, `ocr_max_image_seconds=180.0`, `embedded_max_image_seconds=600.0`. Для Direct допустимы ctx 32768/65536;
увеличение контекста/генерации требует отдельного измерения. Остальные backend
параметры и политика SSL/proxy не менялись.

## Воспроизведение (только явно выбранный локальный backend)

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest --junitxml=.evidence/hybrid/regression.xml
uv run python scripts/qualify_tables.py data --output data/new-private-run
uv run python scripts/benchmark_ollama.py data --output data/new-private-benchmark
uv run python scripts/generate_holdout.py --output data/new-holdout --seed 713091 --count 8
uv run python scripts/qualify_tables.py data/new-holdout --output data/new-holdout-run
uv run python scripts/replay_tables.py data/new-private-run --output data/new-private-replay
```

`qualify_tables.py` ограничивает calls/time, сохраняет digest до/после, размеры ROI,
usage, runner и latency. `benchmark_ollama.py` имеет жёсткий максимум 18 обращений:
два фиксированно выбранных реальных входа и два независимых synthetic control,
8K/16K, stop/no-stop, generate/chat, 75% resize, JPEG95, один ROI Text/Table.
Coverage реального изображения без gold — `null`, а не размер OCR-строки.
64K не запускается без обнаруженной нехватки 32K. Replay сверяет canonical
позиции/значения/spans на записанных ответах и **не является живым OCR**.
Все эти выходы приватны и исключены из Git/CI/handoff. Каталог output должен быть новым.

## Отдельный SDK candidate

[Официальный SDK](https://github.com/zai-org/GLM-OCR) описывает layout + region OCR.
Его [selfhosted dependencies](https://github.com/zai-org/GLM-OCR/blob/main/pyproject.toml)
включают Torch, torchvision и Transformers. В проверенном
[config.yaml](https://github.com/zai-org/GLM-OCR/blob/main/glmocr/config.yaml)
MaaS включён, layout задаётся Hub ID, параллелизм OCR равен 32. Это не drop-in
режим LocalOCR. Нужны pin commit/weights, локальные пути, отключённый MaaS и
проверка без сети с одним worker. SDK не установлен, веса не загружены, Windows
Portable не расширен. Следующий шаг — отдельная offline-квалификация layout,
затем независимых text boxes для безрамочных таблиц; новых бесконтрольных retries нет.
