Первая линия LocalOCR candidate. Автономное распознавание изображений таблиц
через доступный локальный/LAN Ollama с glm-ocr:latest. Модель не включена.
Распакуйте весь ZIP, запустите LocalOCR/LocalOCR.exe; CLI находится в
LocalOCR/LocalOCR-CLI/LocalOCR-CLI.exe. Python/Excel/uv/Codex не нужны.
Проверьте SHA256 перед запуском. Подробные инструкции в README внутри ZIP.

Candidate: текст OCR и сложная геометрия требуют независимой сверки.
Слабые линии и объединения на границе длинных фрагментов могут дать REVIEW/FAILED.
Не заявляется production-ready или измеренный процент точности.

## Корректирующий Excel/OCR candidate

Новые XLSX не содержат комментариев. Ширина и высота рассчитываются локально по
содержимому; прежние XLSX с comments остаются доступны qualification-инструменту.
Исходные OCR-наблюдения записываются только при включённой diagnostics.

Большие и неполные OCR-ответы запускают ограниченное дробление регионов. Фрагменты
сшиваются только по совпавшему OCR-перекрытию и подтверждённой геометрии; сомнения
остаются REVIEW или FAILED. Частичный живой прогон воспроизвёл отказы GLM-OCR;
полный набор отложен по запросу пользователя. Повышение точности не заявляется.
Открытый внешний край определяется по согласованным концам линий; разрезы
рулёных таблиц выбираются вне геометрически подтверждённых rowspan-групп.
Ошибка Ollama TOKEN_REPEAT_LIMIT выделяется отдельно от done_reason=length.

Корректирующий пакет после v0.4: единая VCS identity source/package/frozen,
сохранение десятичной разрядности без массовых XLSX comments,
строгая immutable release verification и локальный manual-gold quality workflow.
Exclusive output требует hardlinks; FAT/exFAT не поддерживаются этим режимом.

Provider candidate: Direct Ollama, OpenWebUI Ollama Proxy/Chat Completions and
managed local GLM-OCR llama-server. OpenWebUI token is plain text in user JSON.
Lite contains no model. Portable F16 is included only after real Windows CPU
vision qualification; when included, assemble all split assets locally with the
supplied PowerShell script to run on a disconnected PC. No runtime downloads.
OpenWebUI live connection and historical human OCR gold remain PENDING.

Embedded GPU candidate: exactly Auto/GPU/CPU, automatic CUDA → Vulkan selection,
confirmed full language + vision offload required; strict GPU never falls back to
CPU. Portable includes pinned CUDA 12.4 runtime DLLs and Vulkan engine alongside
CPU and the single F16 model pair. Linux RTX A4000 synthetic XLSX qualification
passed; Windows GPU hardware remains GPU_HARDWARE_PENDING. See workflow evidence
for the exact Windows CPU/assembled bundle result. No Windows GPU VERIFIED claim.

GUI connection/OCR log now reports actual HTTP requests, response fragments/status,
TLS/DNS/socket causes and timeout stages, with token and image omission. System
proxy is disabled by default (trust_env=False), redirects disabled, TLS verified
by default. OpenWebUI Proxy and Chat permit explicit TLS verification and system
proxy settings in GUI/config/CLI; Direct and Embedded keep fixed safe defaults. Live
user OpenWebUI connection remains PENDING without its configured server credentials.

Final diagnostics correction: configured tokens are omitted from final exception
strings and Qt worker errors as well as transport events. Original technical causes
remain chained. Invalid-URL constructor errors explicitly report URL_INVALID.

Native GPU OOM/device errors occurring after readiness are preserved as technical
causes of failed inference; ordinary OCR output is discarded. Windows qualification
records actual model-startup and per-request inference timing separately.

GPU discovery preserves original --list-devices diagnostics even when the command
exits zero with no usable device: driver mismatch, failed backend DLL loading and
software renderers remain observable. Startup timeouts include bounded technical
engine output. No GPU claim follows from a successful probe exit code alone.

Windows F16 qualification exercises the shared engine across both synthetic inputs
in one frozen batch, recording one model startup and per-image/per-request latency.
One bounded build-time retry is permitted only for a startup deadline, retaining
first-attempt evidence; synthetic gold failures are not retried. Runtime OCR retry
semantics and the F16 pair are unchanged.

Corrective connection settings: typed config migration retains valid fields and plain
JSON tokens; boolean ssl_verify=True and trust_env=False persist independently.
CLI supports --ssl-verify/--no-ssl-verify and --trust-env/--no-trust-env.
Embedded has a dedicated Qt signal for actual selected runtime, mode, device,
full offload evidence or CPU, and Auto fallback reasons; errors clear stale status.

Portable settings and compact GUI: settings/logs/Embedded lock now share the
executable directory (nested CLI included). Default GUI offers Server (OpenWebUI
Ollama Proxy), strict F16 GPU and F16 CPU. Use --full-gui for advanced settings.
Configure the server URL/model/token in config.json; OpenWebUI user defaults are
ssl_verify=false and trust_env=false. Existing saved booleans are preserved.
Move the complete application folder to a writable location; results remain beside
source images. No runtime settings or credentials are shipped in the ZIP.
