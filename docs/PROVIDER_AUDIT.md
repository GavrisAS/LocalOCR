# Аудит пакета Embedded / OpenWebUI

## A. Verdict

PARTIAL до фактического Windows qualification/release evidence. OpenWebUI proxy/chat
реализованы и проверяются на mocks; реальное соединение PENDING. Embedded F16
не получает PASS от mock lifecycle, одного startup или Linux inference.
Q8_0 — явный отдельный набор, real qualification PENDING. Production readiness
PARTIAL; независимый human gold исторической 35×9 таблицы QUALITY_PENDING.

## B. Git

Существующий private GavrisAS/LocalOCR, исходный и фактический HEAD перед работой
c28d240647a457a8b8907fe87a5edee19767ab91, tag v0.8, 144 исходных теста.
Нет новых пользовательских изменений. Версия следующего push определяется
remote reservation; v0.9 заранее не обещается. SHA/tag/release URL/CI/rerun
окончательно записываются в переносимый FINAL_REPORT после выполнения Actions.
Исторические tags/releases не изменяются; version-bump commits не создаются.

## C. Providers

OCRProvider + create_provider; типизированные Settings, OpenWebUISettings,
EmbeddedSettings. Direct: /api/tags, /api/generate; proxy: /ollama/api/tags,
/ollama/api/generate; chat: /api/models, /api/chat/completions; Embedded:
/v1/models и /v1/chat/completions. Proxy/chat отправляют Bearer. Path prefix,
HTTP(S), домен и произвольный порт допустимы для OpenWebUI. Direct LAN pinning
сохранён. HTTP environment proxy/redirect выключены, verify=True.

AppConfig сохраняет backend, обе пары URL/model, api_token открытым текстом,
тип API и precision; атомарный JSON прежней схемы. Миграция folder/ollama_url
выбирает Ollama без потери значений. GUI показывает только поля режима,
не допускает повторного задания; модель/engine и OCR вне Qt worker UI thread.
CLI прежние параметры и exit codes сохранены, --use-config явно включает JSON.
Нет fallback на другой provider и нет Proxy→Chat авто-переключения.

## D. Embedded

Точные URLs/revisions/SHA256/размеры в scripts/embedded-lock.json:
llama.cpp b11612, commit 10da8c463f735c7eaff904c6474e6cf38dccbe83, Windows CPU
standalone ZIP SHA256 b8456ccb1be98365a5a2227efa5c495508a6a3ebce881c6189a1dbeaaa170b69.
F16 text: ggml-org revision 65a42de1148dbed2297e922b5dbc7d9b70c36578,
SHA256 b06675e983db9593db78603b06f097e48c0cf078b37731c0a09612f4a249cf6f.
F16 mmproj: mradermacher revision 11fad2c98e06d1ca82a1b5bc0c9137ee5758991b,
SHA256 fe5805b3b70f3174d25a912b8d197569eaa8e1e3e6d9777a385b8cc4c622af6c.
Linux CPU: точная пара реально распознала 3×3 и длинную 30×3 таблицы;
0 несовпадений исходного текста, обе XLSX SUCCESS, shapes сохранены.
Windows совместимость остаётся PENDING до runner qualification. Q8_0 text/projector закреплены
отдельно в том же lock, без смешения с F16.

CPU: --flash-attn off, --n-gpu-layers 0, --no-mmproj-offload, --ctx-size 32768,
--parallel 1, --offline. Все пути локальные, относительно frozen executable,
не cwd. Engine окружение очищается от LLAMA_/HF_/MTMD_ overrides.
Один engine на пользователя (process lock + OS file lock), переиспользуется
для папки. Случайные API key/alias исключают чужой сервер при port race.
Проверка authenticated models вместо одного TCP/health. Отмена interrupt HTTP,
terminate/wait/kill только собственного Popen, finally закрывает процесс.
GPU не реализован/не квалифицирован, CPU единственный выбранный режим.

## E. Windows assets

Lite ZIP сохраняется без модели; обязательные frozen GUI/CLI smokes прежние.
Portable — ZIP64 stored, части по 1900 MiB (<2 GiB); потоковый штатный PowerShell
assembly без Python/7-Zip/Интернета на целевой машине. Сверяются части, общий ZIP
и каждый установленный компонент. Model + mmproj: 2 654 789 728 bytes до engine/app.
prepare_embedded.py выполняет downloads только в build, сверяет immutable SHA256,
копирует standalone DLL set и пишет component manifest.

Qualification gate привязан к Windows, precision f16, exact build SHA и manifest
SHA256. Проверяет 3×3 и длинную 30×3 синтетическую таблицу через relocated frozen
CLI → общий pipeline → XLSX/openpyxl, сравнивая реальный original OCR text с
известным source каждого anchor. Нет fixed-row mapping. Firewall запрещает
внешние подключения в runner; GitHub доступ восстанавливается после проверки.
При FAIL/PENDING Portable не публикуется; release notes явно сообщают это.
Published assets скачиваются verify_release, собираются PowerShell и повторно
проходят real qualification. Размеры/digests только из реально созданного release.

## F. Regression

144 baseline теста прошли после provider refactor; итоговая локальная suite —
179 тестов. Source GUI offscreen smoke PASS. Новые тесты: request payload,
401/403/redirect/errors, bounded retry без потери context, in-flight cancellation,
models visibility, plain text config migration, fake subprocess readiness,
reuse/shutdown/timeout/foreign-process protection, no external connect,
shared adapter→canonical→XLSX fidelity, split assembly (на Windows PowerShell),
exact multi-asset rerun. Ruff, format, ty и pytest обязательны Linux/Windows.
Структурные тесты и OOXML fidelity не означают cell-level OCR accuracy.
Исходные validation, numeric fidelity, formulas-as-strings, атомарная запись,
REVIEW/FAILED и cancellation перед публикацией сохранены.

verify_release поддерживает исторический двухфайловый contract и новый
release-manifest exact asset set/tag/SHA/sizes/GitHub digests. Rerun не uploads
и не recreates отсутствующий historical release. Digest вычисляется потоково.

## G. Quality

Mocks измеряют контракт и pipeline; synthetic known source измеряет только
конкретные тестовые изображения. Human gold 35×9 QUALITY_PENDING.
Приватные изображения/XLSX/OCR logs, модели и binaries не коммитятся.

## H. Limitations/PENDING

Real OpenWebUI, независимый human gold, чистая Windows VM, GPU и Q8_0.
Любое не пройденное Windows F16 qualification остаётся FAIL/PENDING независимо
от успешного CI unit tests. Linux evidence только дополнительное.

## I. Usage

Точные команды GUI/CLI и offline PowerShell assembly:
[EMBEDDED_OPENWEBUI.md](EMBEDDED_OPENWEBUI.md).

## J. Handoff

`uv run python scripts/create_handoff.py --providers --output .evidence/provider-handoff`
создаёт allowlisted source.zip/JUnit/audit/aggregate evidence/SHA256SUMS.
Финальные CI/release/qualification JSON и FINAL_REPORT лежат в
.evidence/providers; модели/изображения туда для handoff не включаются.
