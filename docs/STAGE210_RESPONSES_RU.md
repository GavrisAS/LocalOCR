# Stage 2.10: ограниченный fail-soft

Переключатель fail-soft остаётся opt-in. GUI и CLI используют один service.
Один whole-image модельный вызов на файл; максимум min(3, 1 + retries, max_calls)
фактических HTTP OCR attempts, общий image deadline включает retries.
Дополнительного generation retry, region/cell fan-out и смены модели нет.
Обычный многошаговый режим остаётся отдельным историческим режимом: этот cap
относится к fail-soft. Для массовой обработки с ограниченными запросами включите
fail-soft. Никакого повышения точности из числа созданных книг не следует.

## Формат документа

`structured_blocks.py` независимо валидирует HTML и Markdown в порядке появления.
Ошибка или oversized span в одном блоке не отменяет соседнюю валидную таблицу.
Для выбранных GLM-OCR/DeepSeek-OCR допускается один канонически валидный префикс
полностью закрытых HTML-строк до повреждения. Нет добавленных строк/ячеек;
пересекающий границу rowspan и ragged grid отклоняются. Остаток сохраняется как
неразмещённый текст. Префикс явно получает PARTIAL_STRUCTURED/UNRESOLVED.
Markdown separator должен совпадать с шириной каждой строки, явные пустые крайние
ячейки сохраняются. Вложенные таблицы и неоднозначные spans не ремонтируются.
Plain text/пробелы/bbox не доказывают столбцы; TSV требует explicit producer contract.
Таблицы и неразмещённые строки сохраняют внутренний порядок на отдельных листах.
Это format-local координаты, а не подтверждённая геометрия исходного изображения.

`deepseek_layout.py` применяется только к выбранному ID deepseek-ocr (опционально
namespace и tag), независимо от Chat/Proxy/Direct. Консервативная грамматика:
`table`, `text`, `sub_title` в начале блока, затем `[[x1,y1,x2,y2]]`;
целые 0..1000, x1<x2, y1<y2, пробелы/CRLF допускаются. Последовательные metadata
на одной строке допустимы. Значение сразу после закрывающего `]]` сохраняется.
Произвольная inline-фраза с похожим синтаксисом не удаляется. Неполные,
невалидные, вложенные или неизвестные варианты сохраняются буквально с
LAYOUT_METADATA_UNCERTAIN для распознанного префикса в начале блока. Они требуют
ручной проверки и не образуют сетку. Сам маркер table не является таблицей.
В synthetic fixtures однозначные metadata полностью исключены из значений.
Windows raw с такими маркерами отсутствуют: реальная грамматика/остаточная утечка
на них PENDING_RAW_REPLAY. Наблюдённые исторические DeepSeek outputs использовали
другой синтаксис grounding. Более широкая грамматика без первичных данных не заявлена.

Raw response и layout provenance сохраняются только при opt-in diagnostics.
Offsets layout относятся к тексту после существующего inert/control filter;
оригинальный response хранится отдельно. Число удалённых маркеров/символов и число
неоднозначных префиксов доступны как отдельные агрегаты. Метаданные не становятся
значениями XLSX. Координаты никогда не объединяют таблицы. Лимиты: 4M символов,
100000 строк raw, 4096 layout-кандидатов, bbox до 256 символов, 64 таблицы,
глубина HTML 128, 200000 тегов/блок, канонический предел 100000 slots/таблицу.
Parser/writer остаются в disposable worker с deadline и memory cap; публикация
только после readback и проверки cancellation в родителе. Literal strings,
reversible XML escaping, длинные ячейки и atomic/no-overwrite сохранены.

## Completion / совместимость

`response_protocol.py`, schema ocr-completion/1, разделяет finish_state:
GENERATION_LIMIT_CONFIRMED только при API reason=length; NORMAL_STOP только по
явному stop (Ollama требует done=true); иначе FINISH_UNKNOWN.
`done=false`/неboolean — TRANSPORT_INCOMPLETE, а не доказанный generation limit.
Для отсутствующего done нет утверждения об усечении. Malformed envelope даёт
MALFORMED_API_RESPONSE; невалидное/пустое HTTP JSON — TRANSPORT_INCOMPLETE.
Незакрытые HTML-теги/Markdown fence дают RESPONSE_INCOMPLETE_SUSPECTED отдельно от
API state; parser failure сам по себе не считается length. Подозрение не вызывает
повторного OCR. При length полезный текст экспортируется с TRUNCATED_CONFIRMED и
PARTIAL/REVIEW. Совместимый SUSPECTED_TRUNCATION оставлен как deprecated warning,
его нельзя интерпретировать как подтверждение length; смотрите versioned completion.
Старый журнал читается, история сохраняется. pipeline evidence-grid-2 и
stage210-failsoft/2 меняют fingerprint; прежний XLSX не принимается за новый.

`ocr-content/1` добавляет OCR_CONTENTFUL, content_kind, distinct values,
characters, numeric text tokens, UNPLACED_TEXT и layout counts, сохраняя старые поля.
STRUCTURED_TABLE подтверждает только границы формата/валидность spans, TEXT_ONLY —
наблюдения без сетки; NO_CONTENT не публикует workbook. XLSX_EXISTS, readback,
yield, calibration accuracy и доступность настоящего сервера — разные факты.
HTTP status/retry backoff/endpoint family сохраняются безопасными полями без URL,
токенов и OCR. Сетевые правила/TLS/proxy/пустой Bearer не изменены.

## Qualification

Публичные synthetic fixtures: tests/fixtures/stage210.json; unit/property-like,
protocol/budget/resume tests: tests/test_stage210_responses.py.
Offline replay: scripts/replay_stage210.py; private manifest/raw/GOLD не входят в Git.
Сравнение baseline запускается отдельным процессом с --source-root на точный v0.31;
кандидат получает те же проверенные raw bytes. Matching: first table, фиксированные
row/col/span, без смещений; text exact после outer strip. Дополнительный text multiset
игнорирует размещение и ограничивает multiplicity. Это calibration, не holdout.

Frozen qualification расширена реальными loopback Chat/Proxy GLM HTML и DeepSeek
bbox/Markdown с точным readback значений, API length/malformed/timeout, controls
двух GUI, frozen child parser/writer deadlines/crash/cancel и следующим файлом.
Инъекции deadline/fault существуют только в qualification harness, не в runtime.
Windows Job process tree дополнительно проверяется source suite на Windows.
Настоящий OpenWebUI Chat не получает SERVER_LIVE_PASS по synthetic loopback.
PRODUCT_RELEASE=NO_GO до принятия владельцем реальной Windows-сборки.
