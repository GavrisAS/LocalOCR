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
