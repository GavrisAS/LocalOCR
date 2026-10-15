# LocalOCR invariants
Python 3.14, src package, uv and committed lockfile. GUI and CLI call the same service.
Runtime may contact only the selected local/LAN Ollama, explicitly configured OpenWebUI,
or owned loopback Embedded engine. No redirects, model downloads, generated code or telemetry. HTTP environment
proxies are opt-in for explicitly configured OpenWebUI only. OpenWebUI tokens are plain text in user JSON. TLS certificates are verified by default; only OpenWebUI permits explicit opt-out.
Never infer missing values or ambiguous cell placement. Preserve source images.
Writer consumes validated canonical tables; OCR strings never become formulas.
Cancellation must prevent publication of unfinished workbooks. Sensitive OCR artifacts
are opt-in and never committed. Do not commit local documents, images, logs or archives.
Run uv run ruff check ., uv run ruff format --check ., uv run ty check, uv run pytest.
Releases use strictly MAJOR.MINOR, immutable remote tags reserved before checks/build,
one per main push; reruns reuse SHA reservation. No force pushes or version bump commits.
Build and frozen smoke on Windows before publishing a candidate release.
Embedded exposes Auto/GPU/CPU only. Strict GPU requires proven full LLM and vision
offload; no CPU fallback. Keep backend binaries isolated and pinned to one commit.
GPU packaged, Linux hardware qualified, and Windows hardware qualified are distinct.
HTTP diagnostics use the common transport and Qt signals; omit tokens/images/OCR text.
