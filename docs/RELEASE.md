# Release

Каждый main push резервирует remote lightweight vMAJOR.MINOR на github.sha.
Первый — v0.1, следующий — v0.2; числовая сортировка, посторонние теги игнорируются.
Rerun ищет existing reservation на том же SHA. Previous github.event.before
должен иметь reservation; иначе wait до 15 минут и явная ошибка. Это сохраняет
порядок близких push без cancel-in-progress и без CI version commits.
Git remote читается каждый раз; коллизии перечитываются, force не используется.
При unexpected tag с другой SHA вместо ожидаемого predecessor workflow
явно завершается ошибкой; следующий номер приблизительно не выбирается.
Сборка/проверки идут после reservation. Неуспех оставляет tag, release отсутствует.
PR/manual/tag pushes не создают версии. Major меняет только пользователь: явно
изменить --major в workflow. Начальная minor новой major-линии — 1.

Публикация: private repo, Windows runner, locked uv, checks, PyInstaller onedir
GUI + CLI, frozen smoke, ZIP + SHA256, prerelease. Generated _build_version.py
включается в EXE и удаляется после сборки. Версия CLI/GUI обязана совпасть с tag.
Исходный pyproject baseline 0.1 не меняется CI; frozen runtime использует reservation.
При rerun published Release не переписывается. GitHub permissions contents:write
должны быть доступны. Произвольная запись release tags третьей стороной запрещена.

## Offline GPU candidate

Portable uses the existing schema-1 streaming split/assembly flow (<1900 MiB parts),
with an additive `gpu_qualification` field. Legacy assemblers still validate every
engine/model size and SHA256. CPU engine remains in `embedded/engine`; CUDA 12.4
engine + cudart/cuBLAS archive and Vulkan engine go into separate `engines` folders.
All engines share b11612/10da8c4. F16 weights/projector are stored once. Lockfile
records upstream URLs/digests/sizes; component manifest records every extracted
DLL/EXE and notice. Retain MIT license and pinned NVIDIA EULA with the bundle.
CUDA Toolkit/Vulkan SDK are build/runtime dependencies of neither Lite nor end user;
compatible vendor drivers are required only for GPU. No runtime download/installer.

A Windows CPU PASS can publish GPU-capable Portable as an explicitly unqualified
GPU candidate (`GPU_HARDWARE_PENDING`); it must not say GPU VERIFIED. Linux hardware
evidence is separate. Clean Windows VM, Windows GPU and internet-disconnected
hardware evidence remain separate qualifications. Existing immutable reservation,
Lite frozen checks, exact manifest and same-SHA rerun remain authoritative.
