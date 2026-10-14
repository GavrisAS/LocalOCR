# LocalOCR invariants
Python 3.14, src package, uv and committed lockfile. GUI and CLI call the same service.
Runtime may contact only the configured local/LAN Ollama. No proxies, redirects, cloud,
model downloads, generated code or telemetry. TLS certificates must be verified.
Never infer missing values or ambiguous cell placement. Preserve source images.
Writer consumes validated canonical tables; OCR strings never become formulas.
Cancellation must prevent publication of unfinished workbooks. Sensitive OCR artifacts
are opt-in and never committed. Do not commit local documents, images, logs or archives.
Run uv run ruff check ., uv run ruff format --check ., uv run ty check, uv run pytest.
Releases use strictly MAJOR.MINOR, immutable remote tags reserved before checks/build,
one per main push; reruns reuse SHA reservation. No force pushes or version bump commits.
Build and frozen smoke on Windows before publishing a candidate release.
