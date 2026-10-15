# LocalOCR

Автономное приложение для преобразования изображений таблиц в Excel через
**glm-ocr:latest**, установленную на явно выбранном локальном/LAN сервере Ollama.
Candidate: точность OCR не гарантируется; результаты требуют сверки с оригиналом.
Нет runtime-зависимости от Codex, ChatGPT, облачных LLM или интернета.

## Windows

Скачайте ZIP и SHA256 из private GitHub Release, проверьте checksum, распакуйте
всю папку. Запустите `LocalOCR/LocalOCR.exe`. Выберите папку, укажите Ollama URL,
нажмите «Проверить подключение», затем «Начать обработку». Результаты — в
`results` внутри выбранной папки. Python, uv, Excel и Codex не нужны.
Модель в дистрибутив не включена. Для LAN Ollama на клиенте устанавливать не нужно.
Модель и сервер предварительно подготавливает администратор; приложение ничего
не скачивает и не запускает `ollama pull`.

Консольный launcher (PowerShell):
```powershell
.\LocalOCR\LocalOCR-CLI\LocalOCR-CLI.exe --version
.\LocalOCR\LocalOCR-CLI\LocalOCR-CLI.exe doctor --ollama-url http://192.168.1.100:11434
.\LocalOCR\LocalOCR-CLI\LocalOCR-CLI.exe convert "C:\Таблицы" --output-dir "C:\Результаты" --ollama-url http://192.168.1.100:11434
```

## Из исходников: Linux и Windows

Python 3.14, uv; Linux для Qt нужны libEGL/libOpenGL.
```bash
uv sync --locked
uv run localocr --version
uv run localocr doctor --ollama-url http://127.0.0.1:11434
uv run localocr convert "image.jpg"
uv run localocr convert "/path/to/images" --ollama-url http://192.168.1.100:11434
uv run localocr-gui
make check
make test
make run-gui
```
Эквиваленты make для Windows:
```powershell
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
uv run localocr-gui
```

## Поведение

JPG/JPEG, PNG, BMP, TIFF, WebP; PDF не поддерживается. Один входной файл — один
XLSX, несколько обнаруженных таблиц — отдельные листы. Исходники не изменяются.
Папка по умолчанию без рекурсии. CLI: `--recursive`, `--overwrite`, `--timeout`
(1–7200 секунд на запрос, по умолчанию 300), `--diagnostics`, `--output-dir`,
`--model`, `--ollama-url`. Полный список: `uv run localocr convert --help`.
Совпадающие имена получают расширение и стабильный hash пути. Существующие
результаты пропускаются. Рекурсивный обход исключает каталог результатов.

`SUCCESS`: OCR совпал с найденной геометрией; это не доказательство текстовой
точности. `REVIEW`: структура HTML однозначна, но нет надёжной линейной геометрии
или имеются предупреждения. Лист «Проверка» содержит причины.
`FAILED`: структура/полнота не разрешены, XLSX не публикуется.
JSON-отчёт создаётся для каждого запуска. Ошибка отдельного файла не останавливает batch.
Exit codes: 0 — SUCCESS/SKIPPED; 1 — REVIEW/FAILED (включая полный неуспех batch);
2 — конфигурация/вход; 3 — сервер/модель недоступны; 130 — Ctrl+C.

Безопасность сети: только loopback, RFC1918 и IPv6 ULA. Все DNS-адреса проверяются,
соединение закрепляется за IP, Host/TLS SNI сохраняются. Прокси и redirects
отключены, TLS verification включена. Публичные и link-local адреса отклоняются.
Приложение не обращается к серверам обновлений, лицензирования или телеметрии.

Настройки и ограниченный локальный лог: `%LOCALAPPDATA%\LocalOCR` на Windows,
`$XDG_CONFIG_HOME/LocalOCR` или `~/.config/LocalOCR` на Linux.
Лог и отчёт содержат имена/пути и статусы, но не содержимое ячеек/ответов.
`--diagnostics` сохраняет полные OCR-ответы локально; они могут быть конфиденциальны.

## Ограничения candidate

Геометрия предназначена прежде всего для таблиц с линиями. Слабые/разорванные
границы, произвольный поворот на 90° без EXIF, сложные страницы и объединения,
пересекающие границу длинного фрагмента, могут потребовать ручной обработки.
EXIF orientation и небольшой наклон нормализуются. Многостраничный TIFF
отклоняется, не обрабатывается молча только первая страница.
Нет независимого пользовательского эталона; проценты точности не заявляются.
Ограничения: 40 млн пикселей, 100000 координатных ячеек на таблицу,
4 МБ OCR-текста / 4.5 МБ HTTP-ответа, 32767 символов в ячейке Excel.

Архитектура, тесты и выпуск: [docs](docs/ARCHITECTURE.md).

## Embedded / OpenWebUI

Три режима, CLI flags, plain text config и offline-сборка Portable описаны в
[EMBEDDED_OPENWEBUI.md](docs/EMBEDDED_OPENWEBUI.md). Lite не содержит модель.
Portable F16 распространяется только после real Windows vision qualification.

### Embedded: Auto / GPU / CPU

Вычисления выбираются одним полем GUI или `--device auto|gpu|cpu` в CLI.
Auto пробует CUDA → Vulkan → CPU, GPU пробует CUDA → Vulkan и запрещает CPU,
CPU запускается с `--device none --n-gpu-layers 0 --no-mmproj-offload`.
CUDA/Vulkan — внутренние backend, отдельных переключателей нет. Частичный или
неподтверждённый offload не допускается: нужны все слои LLM и vision backend GPU.
Статус показывает фактическое устройство, подтверждение offload и причину fallback.
Старые настройки получают Auto; старый `embedded/engine` остаётся CPU-комплектом.
`--device` для сетевого provider отклоняется; explicit flag перекрывает `--use-config`.

Portable F16 содержит одну F16-пару и CPU engine в `embedded/engine`, CUDA и Vulkan
в `embedded/engines/{cuda,vulkan}`. Все варианты закреплены на b11612; CUDA 12.4 DLL
включены в архив. Toolkit/SDK, Python и интернет пользователю не нужны; нужен
совместимый драйвер. GPU-capable candidate не означает Windows GPU qualification.
Аппаратный Windows GPU прогон и чистая Windows VM проверяются отдельно.

```console
localocr doctor --provider embedded --precision f16 --device auto
localocr doctor --provider embedded --precision f16 --device gpu
localocr convert C:\Images --use-config --device cpu
```

### Почему не подключается OpenWebUI?

В существующем GUI log сразу видны реальные запросы, ответы и технические причины.
Для базы `https://host:8443/prefix` Proxy использует
`GET https://host:8443/prefix/ollama/api/tags` и
`POST https://host:8443/prefix/ollama/api/generate`; Chat —
`GET https://host:8443/prefix/api/models` и
`POST https://host:8443/prefix/api/chat/completions`.
Не добавляйте endpoint к базовому URL: смотрите фактически отправленный путь.
HTTP 401 означает отказ авторизации; 404 — ответ маршрута/endpoint; 502 — ответ
сервера (возможная проблема upstream). `TLS_CERTIFICATE_VERIFY_FAILED` показывает
ошибку цепочки сертификата, `DNS_ERROR` — ошибку разрешения имени с исходной причиной.
TLS проверяется, redirects запрещены, `trust_env=False`: системные proxy переменные
не используются. Это намеренная сетевая политика, не автоматический диагноз proxy.

Лог можно выделить и скопировать; копия пишется в `localocr.log` рядом с config.json
(Windows `%LOCALAPPDATA%\LocalOCR`, Linux `$XDG_CONFIG_HOME/LocalOCR` либо
`~/.config/LocalOCR`). Токен остаётся в JSON, но скрывается в диагностике;
изображения/base64 и успешный OCR-текст не логируются. CLI: `--debug-http`.
HTTP API доступен и модель видна — ещё не доказательство успешного OCR; Chat явно
сообщает о мягкой проверке, если model ID отсутствует в списке.
