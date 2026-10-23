# Аудит реальных изображений и исправлений Excel

## A. Вердикт

**PARTIAL.** Автоматические Excel gates и 293 локальных теста пройдены. На 17 реальных изображениях выполнена статическая диагностика. После запуска пользователем Ollama выполнен частичный контролируемый live baseline v0.24: 12 завершённых `FAILED`, CASE-13 отменён. Полный прогон остановлен по запросу пользователя. Повтор CASE-01 на исправленном коде также `FAILED`; восстановления ни одного реального документа и улучшения OCR accuracy не заявляется. Реальных XLSX создано 0.

Подтверждены конкретные ошибки геометрии и фрагментации, внесены консервативные исправления; оставшиеся пропуски значимых ячеек/строк GLM-OCR блокируют публикацию книги. Excel не зависит от провайдера: comments удалены, размеры вычисляются локально, типы сохранены. Windows CPU F16 synthetic qualification v0.27 — PASS; это отдельное доказательство для синтетических таблиц, не реальных сканов. Визуальный Windows Excel review, полный real-images rerun, human gold и текущая GPU hardware qualification остаются **PENDING**.

Опубликованный candidate v0.29 — `77e2aa349425bbea5d6c3014f48998cdc4be9710`: Linux/Windows checks, Windows build/frozen smoke, CPU F16 synthetic qualification и независимая проверка опубликованных Portable parts — PASS. Проверено 2026-10-23. Предыдущий v0.28 остановлен Windows pytest из-за отсутствующего `encoding="utf-8"` в новом тесте чтения JSON; исправление включено в `34e54f9`. Локальный полный suite — PASS, 293 теста. Этот итоговый evidence update изменяет только документацию и сохраняется локально, без нового push/release; snapshot аудита внутри v0.29 отражает состояние до завершения его CI.

Улучшение OCR-пути не меняет автоматом статусы реальных документов. Без повторного ответа модели ни один прежний `FAILED` не считается восстановленным и ни один `SUCCESS` не подтверждён заново.

## B. Baseline и OCR

Источник — локальный каталог `./data/`, обход рекурсивный. Найдено 17 изображений размером от 2,276 до 7,991 пикселей по ширине и от 2,016 до 3,564 по высоте; у одного скана есть EXIF-поворот. Среди входных материалов, без созданного нами corrective-rerun, нет прежнего JSON-отчёта и двух исходных XLSX. Оригиналы не изменялись. Прежние статусы и причины ниже взяты из предоставленной пользователем сводки, а не из отсутствующего отчёта.

| Case | v0.24 | Категория из baseline | Повторная обработка |
|---|---|---|---|
| CASE-01 | FAILED | Структурные пропуски | Live v0.24 FAILED, 4 HTTP / 23.95 s → исправленный код FAILED, 3 HTTP / 28.19 s |
| CASE-02 | FAILED | Усечение OCR | Live v0.24 FAILED HTTP 500, 2 HTTP / 18.90 s; промежуточный c012 FAILED, 201.99 s; финальная ревизия NOT_RUN |
| CASE-03 | FAILED | Усечение OCR | Live v0.24 FAILED length, 1 HTTP / 106.50 s; промежуточный c012 CANCELLED; финальная ревизия NOT_RUN |
| CASE-04 | FAILED | Некорректное объединение | Live v0.24 FAILED, 7 HTTP / 35.87 s; after NOT_RUN |
| CASE-05 | FAILED | Неполный фрагмент | Live v0.24 FAILED, 12 HTTP / 25.76 s; after NOT_RUN |
| CASE-06 | FAILED | Структурные пропуски | Live v0.24 FAILED, 8 HTTP / 48.98 s; after NOT_RUN |
| CASE-07 | FAILED | Структурные пропуски | Live v0.24 FAILED, 6 HTTP / 44.61 s; after NOT_RUN |
| CASE-08 | FAILED | Структурные пропуски | Live v0.24 FAILED, 6 HTTP / 38.95 s; after NOT_RUN |
| CASE-09 | FAILED | Структурные пропуски | Live v0.24 FAILED, 6 HTTP / 39.26 s; after NOT_RUN |
| CASE-10 | FAILED | Структурные пропуски | Live v0.24 FAILED, 4 HTTP / 20.88 s; after NOT_RUN |
| CASE-11 | FAILED | Структурные пропуски | Live v0.24 FAILED, 3 HTTP / 17.65 s; after NOT_RUN |
| CASE-12 | FAILED | Неполный фрагмент | Live v0.24 FAILED со структурными пропусками, 10 HTTP / 58.06 s; after NOT_RUN |
| CASE-13 | FAILED | Структурные пропуски | Live v0.24 CANCELLED по запросу пользователя, 1 HTTP / 60.81 s; after NOT_RUN |
| CASE-14 | SUCCESS, 19×15 | Baseline success | NOT_RUN — полный rerun отложен пользователем |
| CASE-15 | FAILED | Усечение OCR | NOT_RUN — полный rerun отложен пользователем |
| CASE-16 | FAILED | Усечение OCR | NOT_RUN — полный rerun отложен пользователем |
| CASE-17 | REVIEW, 35×9 | Baseline review | NOT_RUN — полный rerun отложен пользователем |

Итог исторического baseline по предоставленной сводке: 15 `FAILED`, 1 `REVIEW`, 1 `SUCCESS`; из 15 отказов — 8 структурных пропусков/столбцов, 4 усечения, 2 неполных фрагмента и 1 некорректное объединение. Это отдельная сводка, не результаты сегодняшнего неполного запуска.

Контролируемый live baseline взят из неизменённого `v0.24` / `3c93b4d`, извлечённого в отдельный временный каталог; зависимости и `uv.lock` совпадают. Использованы Ollama 0.40.7, Direct `/api/generate` на loopback, установленная `glm-ocr:latest` F16 (digest `6effedd0dc8aec66ad86c94b8099395376e212f22c87a9d7147c422f7e447be4`), `num_predict=16000`, `num_ctx=32768`, `temperature=0`, `seed=0`, timeout 300 s. Эти настройки, digest модели, версия сервера и SHA256 исходного изображения совпадают у before/after CASE-01. API `/api/ps` показывает 3,966,144,347 байт модели в VRAM; это не strict Embedded GPU qualification. Параметры исторического JSON неизвестны, поскольку файл отсутствует.

В сегодняшнем v0.24 baseline завершены 12 FAILED (69 HTTP POST, около 517.29 s), CASE-13 отменён (1 POST, 60.81 s), CASE-14…17 не запускались. Среди завершённых: 8 структурных пропусков, 1 HTTP 500 repeat-limit, 1 length, 1 invalid merge, 1 incomplete fragment. После первого исследования c012 промежуточный прогон остановлен: 2 FAILED и 1 CANCELLED. Два точечных повтора CASE-01 после исправлений: `34e54f9` — FAILED, 6 POST / 51.19 s; safe-row версия — FAILED, 3 POST / 28.19 s. Ни один из них не считается восстановлением. Все завершённые реальные результаты имеют 0 таблиц, 0 XLSX; REVIEW/SUCCESS не получены. Независимого human gold нет.

Подробности, реальные имена, исходные OCR-ответы, finish reasons, размеры crop, координаты, duration и before/after SHA256 сохранены только в `data/localocr-corrective-rerun/live-20261022-ollama-1/`; сводный файл — `private-comparison.json`. Таблица выше считает реальные HTTP POST, включая transport retry; `run.json.request_count` считает логические OCR-вызовы, транспортные попытки отдельно восстановлены по приватному логу. Отменённые задания не публиковали unfinished XLSX. Полный rerun отложен по явному запросу пользователя.

Первоначальное статическое измерение геометрии после нормализации ориентации нашло 13 кандидатов layout: 6 с сильной поддержкой линий и 7 с частичной; у 4 изображений линии не найдены. Для той ревизии рассчитаны 9 маршрутов по строковым фрагментам, 4 whole-table и 4 адаптивных page-fragment. Это анализ OpenCV, не OCR и не доказательство правильности границ. Относительные имена, области, координаты, baseline и план маршрута — в `data/localocr-corrective-rerun/private-audit.json`. После live-исследования CASE-01 найденная геометрия исправлена с 21×18 на 21×19; подтверждённые безопасные row boundaries записаны в диагностике точечного прогона. Новая геометрия не подменяет OCR-текст.

Подтверждённая по коду root-cause map:

- `Table.grid()` отклоняет любую непокрытую позицию. Парсер HTML также отклоняет усечённые строки и неодинаковую ширину; отсутствующий `<td>` нельзя отличить от пропущенного значения без OCR-координат. Такой текст не сдвигается и не заполняется догадкой.
- `apply_geometry()` требует точного количества строк и столбцов. На статическом наборе обнаружены частичные линии и страницы без сетки, поэтому точное число проекций OpenCV не всегда является достоверной таблицей.
- В v0.24 без найденной сетки выполнялся один OCR всей страницы. Усечение или ошибка парсера не запускали адаптивное дробление.
- Для ответа Ollama `done_reason=length` отличался от `stop`, но ветвь восстановления зависела от распознанной сетки. Статус `stop` сам по себе не подтверждает полноту HTML.
- Ошибка объединения вне границ остаётся структурным отказом. Конфликт текста в перекрывающихся фрагментах теперь оставляет первое наблюдение и варианты в `REVIEW`; конфликт spans не сдвигается автоматически.
- CASE-01 подтвердил пропущенный внешний край: при отсутствии правой рамки согласованные концы горизонтальных линий задают последнюю колонку, которую v0.24 и c012 теряли. Теперь такой край используется только при достаточной повторной поддержке, с `PARTIAL_GRID`. Разброс концов линий не создаёт новый столбец.
- CASE-01 также подтвердил разрезы внутри rowspan-групп. Теперь каждый внутренний разрез проверяется на поддержку горизонтальной линии во всех столбцах. Непрерывная группа сохраняется целиком, даже если выше предпочтительной высоты; повторы также используют эти границы. Отсутствие безопасной границы не разрешает делить merged cell.
- В CASE-02 наблюдался HTTP 500 `prediction aborted, token repeat limit reached`; это отдельная причина, а не `done_reason=length`. Добавлен `TOKEN_REPEAT_LIMIT`: идентичный deterministic запрос не повторяется транспортом, управление передаётся уменьшению региона. OCR POST error body не попадает в обычный лог; технические GET diagnostics сохранены.
- CASE-03 подтвердил настоящее ограничение длины: `done_reason=length`, `eval_count=16000`, 33,896 символов. В CASE-01 все три последних ответа имели `done_reason=stop`, но содержали неполную структуру. Модель пропустила непустую часть шапки и строку, а rowspan вышел за число выданных строк. Добавить пустые ячейки здесь было бы подделкой; workbook не публикуется.

Внесены ограниченные повторы OCR: большие области режутся по наблюдаемым безопасным строковым границам либо по физическим page-регионам без сетки; количество вызовов и глубина ограничены. Несколько возможных длин OCR-перекрытия и фрагмент без новых строк отклоняются. Успешный OCR без надёжной геометрии помечается `REVIEW`. Пустая область без видимого текста и ответ без повторяющейся структуры не принимаются как таблица. Opt-in `run.json` фиксирует этап, регион, маршрут, safe boundaries, endpoint, параметры, завершение/длину ответа, parser/validation error, время и запросы; штатные фрагменты не считаются retries. Подтверждённые инженерные исправления пока не дали пригодного результата в точечном live-тесте.

## C. Excel

В baseline пользователем сообщено 249 и 303 комментария в двух XLSX (552 суммарно). Эти XLSX локально отсутствуют, поэтому число не перепроверено чтением OOXML. Новая запись не добавляет комментарии ни в таблицы, ни в `Проверка`; тесты проверяют загруженную книгу, отсутствие частей `xl/comments/`, comment relationships и VML notes.

Размеры рассчитываются до сохранения по видимой строке и локальным метрикам Pillow: Arial regular/bold при наличии, иначе DejaVu Sans, Liberation Sans или явная консервативная эвристика. Загрузка шрифтов из сети отсутствует. Встроенный Aileron не содержит кириллицу, поэтому его placeholder-ширина больше не используется как измерение кириллических букв. Размер в пунктах переводится в фиксированные логические 96 DPI; системный DPI и пиксели исходного изображения не участвуют. Выбранная семья задаётся ячейкам и стилю Normal, задающему единицы ширины Excel. Результат детерминирован для одинаковых локальных шрифтов; равенство размеров между системами с разными шрифтами не заявляется.

Ширина ограничена 8–52 единицами, высота строки — 150 пунктами; длинные значения переносятся. Учитываются переносы строк, жирные заголовки, вертикальные и повёрнутые подписи, merged-ячейки; при rowspan дополнительная высота распределяется с учётом оставшегося места в строках. Геометрия исходного изображения больше не назначает итоговые размеры. Если лимит может обрезать отображение, `DISPLAY_LIMIT` попадает в `Проверка`, issues и batch JSON; результат становится `REVIEW`.

Три синтетические книги и измерения сохранены только локально в `data/localocr-corrective-rerun/synthetic-excel-qa/`. В них 0 comments, сохранены объединения, есть числовые форматы и лист проверки при превышении лимита. Пример измерений: длинное кириллическое название — ширина 52 и высота строки 34.5 пункта; чрезмерный текст — высота 150 с `DISPLAY_LIMIT`. Автоматический OOXML/dimension PASS не заменяет визуальный просмотр Windows Excel, который остаётся **PENDING**.

Сохранены числовая семантика и форматы (`5,50` → число с `0.00`), ведущие нули и идентификаторы как текст, inert строки `=...`, spans, стили, freeze panes, REVIEW-заливка и отмена до публикации. Точное совпадение с Excel AutoFit на произвольных шрифтах не заявляется.

`quality.py` продолжает читать исторические comments. Новые исходные OCR-наблюдения доступны только при opt-in diagnostics в `observations.json`; штатная папка `results` дополнительными файлами не засоряется. Без sidecar или исторического comment экспорт помечает сравнение `RAW_TEXT_UNAVAILABLE` и не выдаёт значение восстановленной ячейки за исходный OCR. Windows CPU и developer GPU qualification переведены на этот sidecar и отдельно проверяют отсутствие comments в новых XLSX. Последний GPU hardware прогон не выполнялся.

## D. QA

- `UV_CACHE_DIR=/tmp/localocr-uv-cache uv sync --locked` — PASS.
- `UV_CACHE_DIR=/tmp/localocr-uv-cache uv run ruff check .` — PASS.
- `UV_CACHE_DIR=/tmp/localocr-uv-cache uv run ruff format --check .` — PASS.
- `UV_CACHE_DIR=/tmp/localocr-uv-cache uv run ty check` — PASS.
- `UV_CACHE_DIR=/tmp/localocr-uv-cache uv run pytest` — PASS, 293 теста за 37.68 секунды, Python 3.14.8. Loopback HTTP fixtures запускались с разрешённым bind.
- Фокусные проверки покрывают отсутствующие наружные рамки, разнобой концов линий, protected rowspan groups, false/unique OCR overlap, разницу между обычными фрагментами и retries, UTF-8 JSON, `TOKEN_REPEAT_LIMIT`, отсутствие чувствительного POST body в логах, comments/OOXML и content sizing. Моки подтверждают алгоритм и безопасность, а не GLM-OCR accuracy.
- Windows build/frozen smoke v0.27 — PASS; GUI simple/full, вложенный CLI, portable paths, Unicode, запись XLSX без comments. Linux/Windows lint/type/pytest checks — PASS. Run: https://github.com/GavrisAS/LocalOCR/actions/runs/39747662199.
- Настоящая Windows CPU F16 qualification v0.27 — PASS: manifest `build_commit=491a54adf1e32776e1234ab65aee0b62a37f042c`, `network_isolated=true`, один общий CPU engine, синтетические 3×3 и 30×3, 0 text mismatches и правильные значения; batch 282.57 секунды. Raw OCR сверяется по opt-in sidecar. Модель GLM-OCR F16 и pinned llama.cpp b11612 / `10da8c463f735c7eaff904c6474e6cf38dccbe83` не менялись. Первичная, assembled и независимая квалификация скачанных опубликованных Portable parts в этом run — PASS.
- v0.28 Windows pytest — FAIL, 285 passed / 1 failed: новый тест читал UTF-8 JSON через системную cp1252. Runtime уже корректно записывал REVIEW, проблема относилась к тесту; явная UTF-8 кодировка исправлена. Сборка/релиз v0.28 не запускались. Run: https://github.com/GavrisAS/LocalOCR/actions/runs/39751469538.
- v0.29 — PASS: [CI](https://github.com/GavrisAS/LocalOCR/actions/runs/39756985199), [Windows candidate workflow](https://github.com/GavrisAS/LocalOCR/actions/runs/39756985133), включая Linux/Windows checks, frozen GUI/CLI, сборку и `verify-published-portable`. Скачанные `release-manifest.json` и `portable-manifest.json` указывают на `77e2aa349425bbea5d6c3014f48998cdc4be9710`; SHA256 portable manifest совпал с release manifest. Windows CPU F16: `network_isolated=true`, `shared_engine=true`, одна qualification attempt, таблицы 3×3 и 30×3, 0 text mismatches, `values_match=true`, правильные типы; batch 307.497 секунды. Это реальная модель на синтетических входах, не успешная квалификация сканов пользователя.
- Windows GPU hardware qualification остаётся `GPU_HARDWARE_PENDING`; текущая Linux GPU hardware qualification не подтверждается этим отчётом. CPU synthetic PASS не доказывает GPU offload или точность на сканах пользователя.
- Живой GLM-OCR — выполнен частично после запуска Ollama пользователем; полного прогона нет по его запросу. Восстановление CASE-01 — **FAIL**, точность не измерена. Регрессия по двум исходным XLSX — **PENDING_INPUT**, потому что эти файлы отсутствуют; CASE-14/17 повторно не запускались. Визуальный Windows Excel review — **PENDING**.

## E. Release и приватность

Исходная ревизия — `3c93b4db4e39aa5c20b0648e1feb083044ad1e88`, tag `v0.24`. Основные исправления — `3a6c3a9dcae1cba76775bf50d03665ac74e5b65b`; content sizing и статусы уточнены в `7114e421a0f37b72244b5c0430277119a5bb18e8`; live root-cause fixes — `34e54f92ee905116190e8e322baad3e589564dbd` и `cf0b8d1fe7420cd221cde7f28e83b259fb00aa04`. Репозиторий `GavrisAS/LocalOCR` остаётся PUBLIC.

| Tag | SHA | Подтверждённый результат |
|---|---|---|
| v0.25 | 291be0ba6a48c1dc1bc00769ed4816d0d79d0213 | Reservation сохранена; Windows CLI smoke на белом тестовом изображении FAILED; релиз не создан |
| v0.26 | 9947ee99b59dd3c3d2f1ef04f2fbad4964e98ac7 | Lite candidate; checks/frozen PASS; F16 qualifier зависел от удалённых comments, Portable не опубликован |
| v0.27 | 491a54adf1e32776e1234ab65aee0b62a37f042c | Lite + Portable candidate, Windows CPU F16 synthetic PASS через observations sidecar |
| v0.28 | c012be693c5e008ad7b2d48546431647c745a72e | Reservation сохранена; Windows JSON fixture test FAILED по кодировке; сборка и release не выполнены |
| v0.29 | 77e2aa349425bbea5d6c3014f48998cdc4be9710 | Lite + Portable prerelease; Linux/Windows checks, frozen smoke, CPU F16 synthetic и проверка опубликованных Portable parts PASS |

Выпуски: [v0.26](https://github.com/GavrisAS/LocalOCR/releases/tag/v0.26), [v0.27](https://github.com/GavrisAS/LocalOCR/releases/tag/v0.27). Evidence v0.27 доступна в `portable-manifest.json`, полный список SHA256 — в `release-manifest.json`. Run v0.27: https://github.com/GavrisAS/LocalOCR/actions/runs/39747662199. Предыдущие runs: https://github.com/GavrisAS/LocalOCR/actions/runs/39738035675 и https://github.com/GavrisAS/LocalOCR/actions/runs/39740835832.

Ревизии `34e54f9` / `cf0b8d1` и snapshot аудита отправлены одним push `77e2aa349425bbea5d6c3014f48998cdc4be9710`, которому соответствует immutable minor [v0.29](https://github.com/GavrisAS/LocalOCR/releases/tag/v0.29). Удалённые `main`, tag и оба manifest указывают на этот SHA. Release остаётся prerelease; build/frozen smoke/F16/проверка опубликованных Portable parts завершились PASS. Итоговый локальный documentation-only commit не отправляется: новый push в main потребовал бы следующего minor и нового полного release cycle. Код опубликованного candidate этим обновлением не меняется. Никаких patch tags, force push, version bump commits или переиздания прежних assets не было.

Удалённый v0.24 по-прежнему указывает на `3c93b4db4e39aa5c20b0648e1feb083044ad1e88`. Все восемь assets v0.24 имеют прежние даты обновления 2026-10-16, самая поздняя — `2026-10-16T10:37:18Z`; эти assets не менялись.

В корневой `.gitignore` добавлено `/data/`. Проверено: `git check-ignore -v data/00070.jpg` и `git check-ignore -v data/localocr-corrective-rerun/private-audit.json` указывают на это правило; `git ls-files -- data/` пуст. Git index не содержал файлов из `data/`. В коммит, CI artifacts, handoff и release ZIP не включать изображения, отчёты, XLSX, OCR-тексты или private audit.

## F. Ограничения

Синтетические тесты и Windows CPU F16 qualification подтверждают конкретные примеры, безопасную сборку, реакцию на усечение, отсутствие comments и форматы XLSX. На реальных сканах улучшение accuracy не подтверждено: CASE-01 остаётся FAILED, остальные after-результаты не получены. Причины включают пропуски непустых ячеек/строк, неверные spans и генеративные повторы. Перебор фрагментов ограничен; добавление пустых ячеек при пропущенном непустом заголовке запрещено. Полный набор отложен по запросу пользователя до устранения этих причин.

Две исторические XLSX не являются независимым gold и среди текущих входных материалов отсутствуют. OpenCV-линии остаются сигналом, а не гарантией таблицы; неполная геометрия и сложные шапки могут по-прежнему дать FAILED. Без сетки итог остаётся REVIEW; неоднозначные повторы, конфликт spans и несопоставимое перекрытие отклоняются. Повёрнутый текст, слабые линии, пустые ячейки и merges требуют человеческой сверки. Полное восстановление 17 документов, human-verified accuracy и точное совпадение с Excel AutoFit не заявляются.
