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
