# План реализации Embedded / OpenWebUI

Фактическая база: c28d240647a457a8b8907fe87a5edee19767ab91, v0.8.
Рабочее дерево исходно чистое; remote GavrisAS/LocalOCR. Пользователь явно
разрешил OpenWebUI с произвольным HTTP(S) URL и plain text токеном в JSON;
это расширяет прежнее ограничение AGENTS.md только для выбранного OpenWebUI.

1. Узкий OCRProvider и типизированная фабрика; сохранение Settings/OllamaClient.
2. OpenWebUI proxy/chat, сохранение независимых полей, GUI и CLI.
3. Embedded: локальные пути, один subprocess, loopback и случайный API key,
   readiness, bounded cancellation, CPU, без runtime загрузок.
4. Immutable upstream manifest, потоковая offline assembly, квалификационный
   gate перед публикацией Portable. Lite/release reservation сохраняются.
5. Полный regression и отдельные evidence: mocks, Linux inference, Windows
   real F16, frozen и release. Недоступные проверки остаются PENDING.

Не дублировать parser/geometry/writer. Не публиковать Portable как рабочий
без Windows F16 vision inference и длинной таблицы. Human gold QUALITY_PENDING.
