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
