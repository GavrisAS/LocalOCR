# Архитектура

`domain.py`: Cell/CellObservation/Table/TableDocument/ValidationIssue/JobResult.
`tables.py`: собственный HTMLParser и строгий Markdown fallback.
`imaging.py`: Pillow EXIF/RGB, OpenCV threshold/morphology/Hough deskew/контуры.
`ollama.py`: httpx async native API, ограниченный retry, общий deadline,
DNS pinning, проверка адресов, cancellation polling 50 ms.
`service.py`: обнаружение файлов, безопасные имена, layout/OCR/recovery, отчёт.
`excel.py`: только проверенная модель, openpyxl, стили/spans/безопасные значения,
временный XLSX, повторное открытие, атомарная публикация.
`cli.py`: Typer; `gui/app.py`: QtWidgets, QThread, сигналы, Event отмены.
`config.py`: атомарный per-user JSON и rotating log.

GUI/CLI не содержат таблиц или логики OCR. Один service API. Runtime запускает
только обработку данных; не исполняет код/HTML и не вызывает dev-инструменты.
Вся сеть сосредоточена в ollama.py. Настроенный сервер считается доверенным;
сертификаты HTTPS проверяются с исходным hostname.

Сервис не угадывает расположение missing cells. Только явно представленные
пустые td допустимы. REVIEW сохраняет оригинальные значения, FAILED — без XLSX.

## Embedded device selection and HTTP events

`EmbeddedSettings.device_mode` is independent of precision and engine `--device`.
`devices.py` defines ordered runtime candidates, parses actual `--list-devices`,
rejects software Vulkan devices, and requires all LLM layers plus CLIP GPU backend
in startup diagnostics. Runtime probes and model loading are cancellable; failed
owned processes are terminated before the next candidate. Each candidate is tried
once. Strict GPU disallows partial/unconfirmed offload and CPU. Auto reports the
actual failure chain before CPU. CPU disables both language and projector offload.
The pinned b11612 help supports `none`, `all`, and projector offload flags.
A bounded drained pipe captures startup technical output at verbosity 4; completion
output is discarded after readiness. No raw engine output is persisted by default.

`network.py` supplies Qt-independent callbacks and exception classification. The
common HTTP transport builds one httpx Request, logs its actual method/URL, then
sends that same object. Response fragments are bounded to 4096 bytes, exceptions
retain causes, retries each emit events. `create_provider` and `service.convert`
carry the callback, including preflight doctor failure. Worker emits Qt signals;
only the main thread updates QPlainTextEdit (3000 blocks). Rotating application
logging receives the same redacted lines. HTTP routing/auth/payload and TLS/proxy/
redirect policy are unchanged. Connection diagnostics do not prove model access.
