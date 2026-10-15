Первая линия LocalOCR candidate. Автономное распознавание изображений таблиц
через доступный локальный/LAN Ollama с glm-ocr:latest. Модель не включена.
Распакуйте весь ZIP, запустите LocalOCR/LocalOCR.exe; CLI находится в
LocalOCR/LocalOCR-CLI/LocalOCR-CLI.exe. Python/Excel/uv/Codex не нужны.
Проверьте SHA256 перед запуском. Подробные инструкции в README внутри ZIP.

Candidate: текст OCR и сложная геометрия требуют независимой сверки.
Слабые линии и объединения на границе длинных фрагментов могут дать REVIEW/FAILED.
Не заявляется production-ready или измеренный процент точности.

Корректирующий пакет после v0.4: единая VCS identity source/package/frozen,
сохранение десятичной разрядности и оригинального текста в XLSX comments,
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
proxy remains disabled (trust_env=False), redirects disabled, TLS verified. Live
user OpenWebUI connection remains PENDING without its configured server credentials.
