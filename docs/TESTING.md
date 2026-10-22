# Проверки

Воспроизведение: uv sync --locked; make check; make test.
pytest использует локальный ThreadingHTTPServer, без живой модели.
Синтетические изображения строятся Pillow в тестах, независимы от прототипа.
Проверяются HTML/spans/повреждения/script/Markdown, OOXML roundtrip, формулы,
атомарность/отмена, изображения разных размеров/EXIF/наклон, геометрические
фрагменты, CLI batch/Unicode/коллизии/ошибки, конфигурация/Qt responsiveness,
remote version reservation, timeout/JSON/redirects/proxies/сеть.

CI проверяет Linux и Windows. Release повторяет проверки после tag reservation,
собирает GUI и console onedir на Windows, запускает реальное Qt-окно и
frozen CLI через HTTP mock с XLSX roundtrip. Успех PyInstaller недостаточен.
Реальный GLM-OCR и пользовательские данные не требуются CI.

Результаты реальных запусков и ограничения фиксируются отдельно в AUDIT.md.
Не считать mock evidence доказательством качества реальной модели.

## GPU and HTTP diagnostics qualification

Run `uv sync --locked`, `make check`, `QT_QPA_PLATFORM=offscreen uv run pytest`.
Device/network tests exercise candidate order, strict GPU failure, CPU flags,
software devices, incomplete proof, migrated settings and CLI semantics, real Qt
worker delivery on doctor and batch preflight errors, HTTP statuses and redirects,
actual prefixed URLs, POST payload model IDs, TLS/DNS/socket causes, typed timeouts,
bounded bodies and image omission. Existing fidelity/cancellation tests remain.

Hardware qualification (explicit build/dev command; never downloads):

```console
uv run python scripts/qualify_gpu.py --engine embedded/engines/cuda/llama-server.exe --model embedded/models/f16/model.gguf --mmproj embedded/models/f16/mmproj.gguf --output .evidence/gpu/report.json
```

This runs the same pinned F16 pair on CPU/GPU/Auto, synthetic 3×3 and 30×3 through
the shared canonical validator and XLSX writer, checks opt-in OCR observations,
absence of XLSX comments, shape and cell types, and records actual
backend/device/offload, engine/model hashes, cold
model load and inference latency separately. It fails on synthetic gold mismatch.
RTX A4000 is the target; Linux evidence does not qualify Windows CUDA/Vulkan.
Windows CPU frozen qualification and reassembled Portable checks stay mandatory.
No software test or packaged DLL permits declaring GPU hardware PASS.

Windows frozen qualification processes both fixtures in one actual CLI folder batch,
checks a single shared engine startup, and verifies both workbooks against gold.
Only ENGINE_STARTUP_TIMEOUT may trigger one build-time requalification; the first
failed report is retained. A cell/type/shape mismatch fails immediately.

Portable/simple GUI: tests/test_runtime_simple.py, test_gui_config.py,
test_connection_options.py. Autouse ROOT_OVERRIDE изолирует весь runtime в tmp_path.
Root tests моделируют frozen GUI/вложенный CLI и перемещение; это не проверка EXE.
Windows build выполняет simple и --full-gui frozen smoke; реальные OpenWebUI,
Windows GPU и human gold требуют отдельной проверки. Локальный Linux не заменяет
Windows runner и F16 CPU qualification из existing release gates.
