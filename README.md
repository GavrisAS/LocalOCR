# LocalOCR

Автономное приложение для преобразования изображений таблиц в Excel через
OpenWebUI Ollama Proxy, локальную Embedded GLM-OCR или явно выбранный Ollama.
Candidate: точность OCR не гарантируется; результаты требуют сверки с оригиналом.
Нет runtime-зависимости от Codex, ChatGPT, облачных LLM или интернета.

## Windows

Скачайте ZIP и SHA256 из GitHub Release, проверьте checksum, распакуйте
всю папку в доступное для записи место. Запустите `LocalOCR/LocalOCR.exe`.
Заполните OpenWebUI URL/model/token в `config.json` рядом с EXE или через
`LocalOCR.exe --full-gui`. В простом окне выберите папку,
нажмите «Проверить подключение», затем «Начать обработку». Результаты — в
`results` внутри выбранной папки. Python, uv, Excel и Codex не нужны.
Lite не включает модель; Portable F16 включает локальные компоненты Embedded.
Для LAN Ollama на клиенте устанавливать не нужно.
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
uv run localocr convert "image.jpg" --provider ollama
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
отключены для Ollama; TLS verification включена. Публичные и link-local адреса
Ollama отклоняются. OpenWebUI использует явно заданный URL и сохранённые TLS/proxy настройки.
Приложение не обращается к серверам обновлений, лицензирования или телеметрии.

Настройки и ограниченный локальный лог: `config.json`, `localocr.log` (ротация `.1`, `.2`) рядом с `LocalOCR.exe`;
из исходников — в корне checkout, независимо от CWD.
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
OpenWebUI TLS по сохранённому ssl_verify (default false), redirects запрещены, `trust_env=False`: системные proxy переменные
не используются. Это намеренная сетевая политика, не автоматический диагноз proxy.

Лог можно выделить и скопировать; копия пишется в `localocr.log` рядом с config.json
(рядом с `LocalOCR.exe`, из исходников — в корне checkout). Токен остаётся в JSON, но скрывается в диагностике;
изображения/base64 и успешный OCR-текст не логируются. CLI: `--debug-http`.
HTTP API доступен и модель видна — ещё не доказательство успешного OCR; Chat явно
сообщает о мягкой проверке, если model ID отсутствует в списке.

## Переносимые настройки и два GUI

Без аргументов открывается компактное окно: папка, «Сервер», «GPU (локально)»,
«CPU (локально)», проверка, обработка и отмена. Полные настройки доступны через
`--full-gui`. Оба окна используют тот же Worker и OCR service.

```powershell
.\LocalOCR.exe
.\LocalOCR.exe --full-gui
.\LocalOCR-CLI\LocalOCR-CLI.exe doctor --use-config
```

В ярлыке Windows поле Target: `"D:\LocalOCR\LocalOCR.exe" --full-gui`.
Поле Start in не влияет на пути. Из исходников: `uv run localocr-gui`,
`uv run localocr-gui --full-gui`, `uv run localocr doctor --use-config`.

В комплекте `D:\LocalOCR\` находятся `LocalOCR.exe`, `config.json`,
`localocr.log`, `localocr.log.1`, `localocr.log.2`, `embedded.lock`.
Вложенный `LocalOCR-CLI\LocalOCR-CLI.exe` использует эти же файлы.
Из исходников корень — checkout, вычисленный из расположения модуля.
Переносите всю директорию, включая `_internal`, `embedded` и `LocalOCR-CLI`.
Lite и Portable в разных каталогах имеют независимые настройки.
Каталог должен быть доступен для записи; Program Files не рекомендуется.
Администратор не требуется. При ошибке записи приложение сообщает об ошибке,
без перехода в пользовательский каталог.

На первом старте создаётся JSON без данных сервера. Заполните три пустые строки
самостоятельно или откройте полный GUI. Пример без учётных данных:

```json
{
  "provider": "openwebui",
  "openwebui_api": "proxy",
  "openwebui_url": "",
  "openwebui_model": "",
  "api_token": "",
  "ssl_verify": false,
  "trust_env": false,
  "precision": "f16",
  "embedded_device": "auto",
  "simple_mode": "server"
}
```

Токен хранится обычным текстом в этом JSON. Пользовательские defaults OpenWebUI:
`ssl_verify=false`, `trust_env=false`; переключатели есть в полном GUI и действуют
для Proxy и Chat. Сохранённые boolean при миграции не меняются. Остальные провайдеры
проверяют TLS. Пустые URL/model/token блокируют серверную задачу простого окна.
«Сервер» всегда использует OpenWebUI Ollama Proxy; GPU — Embedded F16, strict GPU
(CUDA → Vulkan, без CPU fallback); CPU — Embedded F16 CPU-only. Выбор режима
не меняет скрытые параметры полного окна. CLI с `--use-config` читает общий JSON,
явные флаги имеют приоритет.

Сохранение JSON атомарное: временный файл рядом, затем `os.replace`. При наличии
portable JSON старые каталоги не читаются. При отсутствии допускается однократный
импорт старого config из `%LOCALAPPDATA%\LocalOCR` (Linux: XDG/`~/.config/LocalOCR`):
только чтение, старые файлы не изменяются, логи не переносятся. Ошибка чтения
не блокирует defaults; новый путь показывается при незаполненной конфигурации.
Шаблон в ZIP не поставляется, поэтому обновление не перезаписывает настройки.

OCR-результаты остаются в `results` рядом с исходными изображениями: XLSX,
атомарные временные XLSX и JSON-отчёты. Папка изображений задаётся пользователем.
Опциональный `--diagnostics` сохраняет чувствительные OCR-ответы в
`<корень Portable>/diagnostics/<имя результата>/`; по умолчанию выключен.
