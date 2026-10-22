# Аудит реальных изображений и исправлений Excel

## A. Вердикт

**PARTIAL.** Excel gates и синтетическая регрессия пройдены; все 17 файлов из `./data/` инвентаризированы, но живой OCR-перезапуск не выполнен: локальный Ollama на `127.0.0.1:11434` недоступен, другой провайдер не подтверждён. CI и Windows frozen GUI/CLI smoke прошли в v0.26. Встроенная Windows F16 qualification выявила устаревшую зависимость qualification от Excel comments, уже удалённых из новых книг; исправление переводит её на opt-in observations sidecar. Повторная F16 qualification для следующего candidate **PENDING**.

Улучшение OCR-пути не меняет автоматом статусы реальных документов. Без повторного ответа модели ни один прежний `FAILED` не считается восстановленным и ни один `SUCCESS` не подтверждён заново.

## B. Baseline и OCR

Источник — локальный каталог `./data/`, обход рекурсивный. Найдено 17 изображений размером от 2,276 до 7,991 пикселей по ширине и от 2,016 до 3,564 по высоте; у одного скана есть EXIF-поворот. В каталоге сейчас нет прежнего JSON-отчёта и двух исходных XLSX. Оригиналы не изменялись. Прежние статусы и причины ниже взяты из предоставленной пользователем сводки, а не из отсутствующего отчёта.

| Case | v0.24 | Категория из baseline | Повторная обработка |
|---|---|---|---|
| CASE-01 | FAILED | Структурные пропуски | PENDING — провайдер недоступен |
| CASE-02 | FAILED | Усечение OCR | PENDING — провайдер недоступен |
| CASE-03 | FAILED | Усечение OCR | PENDING — провайдер недоступен |
| CASE-04 | FAILED | Некорректное объединение | PENDING — провайдер недоступен |
| CASE-05 | FAILED | Неполный фрагмент | PENDING — провайдер недоступен |
| CASE-06 | FAILED | Структурные пропуски | PENDING — провайдер недоступен |
| CASE-07 | FAILED | Структурные пропуски | PENDING — провайдер недоступен |
| CASE-08 | FAILED | Структурные пропуски | PENDING — провайдер недоступен |
| CASE-09 | FAILED | Структурные пропуски | PENDING — провайдер недоступен |
| CASE-10 | FAILED | Структурные пропуски | PENDING — провайдер недоступен |
| CASE-11 | FAILED | Структурные пропуски | PENDING — провайдер недоступен |
| CASE-12 | FAILED | Неполный фрагмент | PENDING — провайдер недоступен |
| CASE-13 | FAILED | Структурные пропуски | PENDING — провайдер недоступен |
| CASE-14 | SUCCESS, 19×15 | Baseline success | PENDING — провайдер недоступен |
| CASE-15 | FAILED | Усечение OCR | PENDING — провайдер недоступен |
| CASE-16 | FAILED | Усечение OCR | PENDING — провайдер недоступен |
| CASE-17 | REVIEW, 35×9 | Baseline review | PENDING — провайдер недоступен |

Итог baseline по предоставленной сводке: 15 `FAILED`, 1 `REVIEW`, 1 `SUCCESS`; из 15 отказов — 8 структурных пропусков/столбцов, 4 усечения, 2 неполных фрагмента и 1 некорректное объединение. Новых OCR-XLSX не создано, длительность и число запросов реального перезапуска неизвестны. Независимого human gold нет.

Локальное измерение геометрии после нормализации ориентации нашло 13 кандидатов layout: 6 с сильной поддержкой линий и 7 с частичной; у 4 изображений линии не найдены. Для статической диагностики рассчитаны 9 маршрутов по строковым фрагментам, 4 маршрута whole-table и 4 адаптивных page-fragment маршрута. Это анализ OpenCV и ветвей кода, не результат OCR и не доказательство правильности границ. Относительные имена, размеры областей, координаты границ, baseline и план маршрута хранятся локально в `data/localocr-corrective-rerun/private-audit.json`; файл игнорируется Git.

Подтверждённая по коду root-cause map:

- `Table.grid()` отклоняет любую непокрытую позицию. Парсер HTML также отклоняет усечённые строки и неодинаковую ширину; отсутствующий `<td>` нельзя отличить от пропущенного значения без OCR-координат. Такой текст не сдвигается и не заполняется догадкой.
- `apply_geometry()` требует точного количества строк и столбцов. На статическом наборе обнаружены частичные линии и страницы без сетки, поэтому точное число проекций OpenCV не всегда является достоверной таблицей.
- В v0.24 без найденной сетки выполнялся один OCR всей страницы. Усечение или ошибка парсера не запускали адаптивное дробление.
- Для ответа Ollama `done_reason=length` отличался от `stop`, но ветвь восстановления зависела от распознанной сетки. Статус `stop` сам по себе не подтверждает полноту HTML.
- Ошибка объединения вне границ остаётся структурным отказом. Конфликт текста в перекрывающихся фрагментах теперь оставляет первое наблюдение и варианты в `REVIEW`; конфликт spans не сдвигается автоматически.

Внесены ограниченные повторы OCR: большие области режутся по наблюдаемым строкам либо по физическим page-регионам без сетки; перекрытие сверяется по полным OCR-строкам; количество вызовов и глубина ограничены. Успешный OCR без надёжной геометрии помечается `REVIEW`. Пустая область без видимого текста и ответ без повторяющейся табличной структуры не принимаются как таблица. Реальные before/after, предупреждения и причины останутся `PENDING` до подключения того же локального/LAN провайдера и настроек.

## C. Excel

В baseline пользователем сообщено 249 и 303 комментария в двух XLSX (552 суммарно). Эти XLSX локально отсутствуют, поэтому число не перепроверено чтением OOXML. Новая запись не добавляет комментарии ни в таблицы, ни в `Проверка`; тесты проверяют загруженную книгу, отсутствие частей `xl/comments/`, comment relationships и VML notes.

Размеры рассчитываются до сохранения по видимой строке и метрикам встроенного `Pillow ImageFont.load_default`, с детерминированной эвристикой при недоступности метрик. Ширина ограничена 8–52 единицами, высота строки — 150 пунктами; длинные значения переносятся. Учитываются переносы строк, жирные заголовки, поворот текста и объединённые ячейки; высота merged-областей распределяется по строкам. Геометрия исходного изображения больше не назначает итоговые размеры. Если ограничение высоты может обрезать отображение, в `Проверка` добавляется `DISPLAY_LIMIT`.

Сохранены числовая семантика и форматы (`5,50` → число с `0.00`), ведущие нули и идентификаторы как текст, inert строки `=...`, spans, стили, freeze panes, REVIEW-заливка и отмена до публикации. Точное совпадение с Excel AutoFit на произвольных шрифтах не заявляется.

`quality.py` продолжает читать исторические comments. Новые исходные OCR-наблюдения доступны только при opt-in diagnostics в `observations.json`; штатная папка `results` дополнительными файлами не засоряется. Без sidecar или исторического comment экспорт помечает сравнение `RAW_TEXT_UNAVAILABLE` и не выдаёт значение восстановленной ячейки за исходный OCR. Встроенная F16 qualification также сверяет raw OCR только по этому sidecar и отдельно проверяет отсутствие comments в новых XLSX.

## D. QA

- `UV_CACHE_DIR=/tmp/localocr-uv-cache uv sync --locked` — PASS.
- `UV_CACHE_DIR=/tmp/localocr-uv-cache uv run ruff check .` — PASS.
- `UV_CACHE_DIR=/tmp/localocr-uv-cache uv run ruff format --check .` — PASS.
- `UV_CACHE_DIR=/tmp/localocr-uv-cache uv run ty check` — PASS.
- `UV_CACHE_DIR=/tmp/localocr-uv-cache uv run pytest` — PASS, 279 тестов, Python 3.14.8. Для тестовых HTTP-серверов разрешён loopback bind вне sandbox.
- GitHub run v0.26: Ubuntu и Windows checks прошли; Windows packaging, frozen GUI/CLI smoke, Unicode-путь и запись XLSX через loopback mock — PASS. Первый run v0.25 CLI smoke не прошёл, потому что тестовое изображение было пустым; сценарий исправлен на видимый синтетический текст. Windows F16 qualification запустилась, но завершилась `Synthetic OCR cells/shape differ from known source`: старый qualifier читал OCR из comments, которых новые XLSX намеренно не содержат. Поэтому v0.26 опубликован как Lite candidate без Portable F16. Исправление qualifier читает `observations.json`; локальные no-grid/retry tests — PASS (2), полный pytest — PASS (280). Повторная Windows F16 qualification для следующего candidate — **PENDING**. Runs: https://github.com/GavrisAS/LocalOCR/actions/runs/39740836030 и https://github.com/GavrisAS/LocalOCR/actions/runs/39740835832.
- Windows GPU hardware qualification остаётся **PENDING** отдельно от CPU F16 synthetic qualification; Linux GPU hardware qualification также не подтверждается этим отчётом.
- Реальный GLM-OCR на 17 изображениях, Embedded F16 и квалификация Linux/Windows GPU: **PENDING**. Проверка `http://127.0.0.1:11434/api/tags` вернула connection refused; ответы модели не получены.

## E. Release и приватность

Исходная ревизия — `3c93b4db4e39aa5c20b0648e1feb083044ad1e88`, tag `v0.24`. Основные исправления внесены в `3a6c3a9dcae1cba76775bf50d03665ac74e5b65b` и `9947ee99b59dd3c3d2f1ef04f2fbad4964e98ac7`. Первый push зарезервировал immutable tag `v0.25` на `291be0ba6a48c1dc1bc00769ed4816d0d79d0213`, но не выпустил assets из-за пустого Windows smoke image. Следующий push зарезервировал `v0.26` на `9947ee99b59dd3c3d2f1ef04f2fbad4964e98ac7`; candidate опубликован: https://github.com/GavrisAS/LocalOCR/releases/tag/v0.26. Windows build/frozen smoke прошли, но F16 qualification не прошла, поэтому Portable F16 assets не добавлены; workflow корректно оставил Lite candidate, `v0.24` и его assets не менялись. Исправление sidecar qualification готовится к следующему push; его tag/CI/release ещё **PENDING**. Runs: https://github.com/GavrisAS/LocalOCR/actions/runs/39738035675, https://github.com/GavrisAS/LocalOCR/actions/runs/39740836030 и https://github.com/GavrisAS/LocalOCR/actions/runs/39740835832; workflow-ссылки: [CI](https://github.com/GavrisAS/LocalOCR/actions/workflows/ci.yml) и [Windows candidate release](https://github.com/GavrisAS/LocalOCR/actions/workflows/release-windows.yml).

В корневой `.gitignore` добавлено `/data/`. Проверено: `git check-ignore -v data/00070.jpg` и `git check-ignore -v data/localocr-corrective-rerun/private-audit.json` указывают на это правило; `git ls-files -- data/` пуст. Git index не содержал файлов из `data/`. В коммит, CI artifacts, handoff и release ZIP не включать изображения, отчёты, XLSX, OCR-тексты или private audit.

## F. Ограничения

Синтетические тесты подтверждают безопасную геометрическую сборку, реакцию на усечение, отсутствие комментариев и форматы XLSX; они не измеряют качество GLM-OCR. Встроенная Windows F16 qualification v0.26 не прошла сравнение OCR cells/shape с synthetic gold из-за прежней зависимости от comments; исправление sidecar пока не подтверждено Windows повторным запуском. Две предоставленные XLSX не являются независимым gold и в текущем `data/` отсутствуют. OpenCV-линии остаются сигналом, а не гарантией таблицы; в страницах без линий результат остаётся `REVIEW`, а несовпадение перекрытий или неполные позиции могут привести к `FAILED`. Любое изменение статуса реальных 17 документов требует живого повторного прогона и последующей human verification.
