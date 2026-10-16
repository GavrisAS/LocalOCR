# Воспроизводимый handoff

Исходники: https://github.com/GavrisAS/LocalOCR, main. Release tags
неизменны и указывают на commit каждой push-версии. Скачать source:

```bash
gh repo clone GavrisAS/LocalOCR
cd LocalOCR
git checkout <release-tag>
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest --junitxml=test-results.xml
uv run localocr doctor
uv run localocr convert /path/to/images
uv run localocr-gui
```

Windows from source: `uv run localocr-gui`; frozen ZIP:
`LocalOCR/LocalOCR.exe`, `LocalOCR/LocalOCR-CLI/LocalOCR-CLI.exe`.
Сборка на Windows:
```powershell
./scripts/build_windows.ps1 -BuildVersion <MAJOR.MINOR>
```
Тестовые evidence доступны в Actions CI artifacts (JUnit Linux/Windows) и
release workflow logs (обязательные GUI и CLI frozen smoke). Имена CI artifacts
включают run_attempt, чтобы rerun не конфликтовал с immutable artifacts.
ZIP и SHA256 публикуются только после проверок. Candidate metadata и
инструкции внутри README, статус реальных проверок — docs/AUDIT.md.

Синтетические входы генерируются самими тестами, дополнительных пользовательских
файлов не требуется. Реальное изображение, прежние OCR результаты и локальная
диагностика в Git/Handoff не включаются. Локальная финальная передача может
содержать `git archive` исходников, обезличенный отчёт и JUnit без документных
данных; исходный пользовательский XLSX остаётся отдельно в .evidence.

Для устранения REVIEW: сверить выделенные наблюдения с изображением вручную
после завершения обработки. Приложение не подставляет значения по догадке.
Рекомендуемая следующая работа: независимый эталон OCR, таблицы со слабыми
границами, перенос vertical spans через границы фрагментов, реальный отдельный
LAN HTTPS сервер. Техническая успешность конвейера не равна оценке точности OCR.

## GPU / diagnostics continuation

See `docs/GPU_DIAGNOSTICS_AUDIT.md` for source-base assumptions, measured Linux
RTX A4000 evidence and Windows GPU limitations. The local `.evidence/audit-v018`
handoff contains the exact committed source snapshot, machine reports, GUI mock
log/screenshot and remote CI/release evidence when available. This directory is
ignored by Git. It must not include model weights, engine binaries or user images.

Portable settings Work Package: source snapshot, SHA256 manifest и локальные
check logs сохраняются в `.evidence/portable-settings/` (не в Git).
Новые tests: tests/test_runtime_simple.py; Windows actual frozen paths:
scripts/portable_smoke.py. По умолчанию compact GUI, --full-gui advanced.
PENDING до отдельных live checks: пользовательский OpenWebUI, Windows GPU
hardware и human gold. Публичная публикация разрешена пользователем; private
release в публичном репозитории недоступен. Старые immutable assets не изменять.
