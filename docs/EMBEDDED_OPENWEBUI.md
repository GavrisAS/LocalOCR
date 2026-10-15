# Три режима OCR

GUI: выберите «Встроенная GLM-OCR», «Ollama» или «OpenWebUI». Для Embedded
выберите F16; Q8_0 доступен при наличии локального комплекта. Проверка загружает
локальную модель, после проверки engine закрывается. Папка обрабатывается одним
процессом. Остановка прерывает запрос и закрывает только собственный engine.
Состояние «готов» означает readiness, а не доказанную точность OCR.

Ollama: URL и Model ID, прежнее значение по умолчанию glm-ocr:latest.
OpenWebUI: пользовательские URL, Model ID, API-токен и тип API; по умолчанию
Ollama Proxy. Токен хранится открытым текстом в обычном пользовательском config.json.
Все поля сохраняются независимо. Старый config.json folder/ollama_url мигрирует
с режимом Ollama. Нет keyring/шифрования/автоматического переключения backend.
Runtime не скачивает модель; HTTP proxies и redirects выключены, TLS проверяется.
OpenWebUI допускает корпоративный домен, HTTPS, порт и prefix; Direct Ollama
по-прежнему допускает только loopback/LAN.

## CLI

```console
localocr doctor --provider ollama --ollama-url http://127.0.0.1:11434 --model glm-ocr:latest
localocr convert IMAGES --provider openwebui --openwebui-api proxy --url https://example.org/prefix --model USER_MODEL --api-token USER_TOKEN
localocr doctor --provider openwebui --openwebui-api chat --url https://example.org/prefix --model USER_MODEL --api-token USER_TOKEN
localocr convert IMAGES --provider embedded --precision f16
localocr convert IMAGES --use-config
localocr doctor --provider embedded --precision f16 --engine PATH --model-path PATH --mmproj-path PATH
```

`--use-config` явно включает сохранённые настройки; flags переопределяют поля.
Без этого флага старые команды используют Ollama. Exit codes: 0 успех,
1 REVIEW/FAILED, 2 настройки/пути, 3 API/engine, 130 Ctrl+C.
GUI/CLI используют общий parser, geometry, validation, openpyxl writer.

## Portable F16

Lite ZIP не содержит модель/engine: работает через Ollama/OpenWebUI.
Portable публикуется только если конкретный Windows CPU F16 bundle проходит
реальное vision inference на синтетических 3×3 и 30×3 таблицах, включая XLSX,
проверку source text каждого anchor и перенос полного bundle в другой каталог.
Квалификация runner выполняется с firewall, запрещающим внешние подключения.
GPU пока не квалифицирован; используется CPU, без PyTorch и без требования NVIDIA.
Q8_0 явно выбирается и закреплён отдельно, Portable Q8_0 пока не публикуется.

Если release содержит Portable: на машине с доступом к GitHub скачайте все
`*.portable-f16.zip.partNNN` (фактические имена `LocalOCR-vMAJOR.MINOR-portable-f16.zip.partNNN`),
`portable-manifest.json` и `assemble_portable.ps1` в одну папку. Перенесите эту
папку на offline Windows ПК. Штатный Windows PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\assemble_portable.ps1 -Destination D:\LocalOCR-Portable
D:\LocalOCR-Portable\LocalOCR\LocalOCR.exe
D:\LocalOCR-Portable\LocalOCR\LocalOCR-CLI\LocalOCR-CLI.exe convert D:\Images --provider embedded --precision f16
```

Скрипт потоково объединяет части (<2 GiB каждая), сверяет размеры/SHA256,
распаковывает ZIP штатным .NET и проверяет каждый компонент. Нужен свободный диск
для частей, объединённого ZIP и распакованного комплекта; модель не помещается
целиком в RAM при сборке. Каталог назначения должен отсутствовать. Python, uv,
Git, Ollama, 7-Zip и Интернет на целевом ПК не нужны. При отсутствии Portable assets
в конкретном release Embedded qualification остаётся PENDING/FAIL, комплект не обещается.

Upstream-кандидаты, точные revision/URLs/SHA256: scripts/embedded-lock.json.
Скачивание разрешено только оператору сборки: `uv run python scripts/prepare_embedded.py
--output dist/LocalOCR/embedded --precision f16`. F16 text ggml-org и F16 projector
mradermacher — закреплённая пара-кандидат; её имена не доказывают совместимость.
Подтверждение существует только при PASS реального qualification evidence.
`--flash-attn off`, `--n-gpu-layers 0`, `--no-mmproj-offload`, context 32768,
parallel 1 и `--offline` — CPU конфигурация кандидата.

Все OpenWebUI результаты на mocks — техническая реализация; реальный сервер
PENDING. Историческая таблица 35×9 — QUALITY_PENDING до независимого human gold.

## Auto / GPU / CPU

GUI exposes exactly three modes for Embedded only. CLI doctor/convert accept
`--device auto|gpu|cpu`; supplying it for a server provider is a configuration error.
Saved `embedded_device` defaults to Auto for old config.json. Explicit CLI selection
wins over saved settings. Settings are frozen for the worker lifetime.
CUDA then Vulkan are probed from their own pinned runtime folders; CPU is permitted
only in Auto/CPU. Legacy `embedded/engine` remains a supported CPU bundle.
Full LLM layer offload and CLIP GPU backend evidence are mandatory; partial offload
is rejected even in GPU mode. No GPU claim is based only on nvidia-smi or file presence.
Startup failures include the runtime error; Auto tries the next candidate once.
GPU inference failures during an existing batch fail the item, without replaying the
batch on CPU. Cancellation terminates the owned process and releases its lock.

## Почему не подключается OpenWebUI?

При базе `https://host:8443/prefix` ожидаются точные маршруты:

| API | Проверка | OCR |
| --- | --- | --- |
| Proxy | `GET https://host:8443/prefix/ollama/api/tags` | `POST https://host:8443/prefix/ollama/api/generate` |
| Chat | `GET https://host:8443/prefix/api/models` | `POST https://host:8443/prefix/api/chat/completions` |

GUI log показывает реально построенный httpx Request: метод, URL, базу, prefix,
порт, model ID, попытку, параметры таймаута, наличие Bearer, HTTP status, Content-Type,
длительность и ограниченный фрагмент ошибки. При отказе до HTTP показывается цепочка
исключений: например `DNS_ERROR`/socket.gaierror, `CONNECT_REFUSED`/errno,
`TLS_CERTIFICATE_VERIFY_FAILED`/ssl.SSLCertVerificationError. Таймауты connect/read/
write/pool/deadline различаются. Неизвестная причина остаётся NETWORK_ERROR.
HTTP 401 → проверьте токен; 403 → доступ; 404 → путь и API; 502 → изучите ответ
reverse proxy/upstream. Это возможные объяснения наблюдаемого статуса.
Redirect показывает Location и не выполняется. Префикс не исправляется по догадке.
`trust_env=False` отключает proxy из окружения, TLS verify=True; отключать TLS или
пробовать HTTP автоматически приложение не будет.

Лог находится в текущем QPlainTextEdit (штатное выделение/копирование) и файле
`localocr.log` рядом с config.json: `%LOCALAPPDATA%\LocalOCR` на Windows,
`$XDG_CONFIG_HOME/LocalOCR` либо `~/.config/LocalOCR` на Linux. CLI имеет `--debug-http`.
Токен хранится обычным текстом в config.json и исключается из диагностических строк.
HTTP 200 не означает OCR PASS: список моделей, видимость model ID и настоящий OCR
проверяются отдельно; Chat сохраняет мягкую проверку видимости.
Реальный пользовательский OpenWebUI без URL/токена в среде остаётся PENDING.
