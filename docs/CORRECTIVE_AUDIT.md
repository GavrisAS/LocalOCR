# Корректирующий аудит после v0.4

Исторический отчёт: разделы о комментариях описывают поведение прежних версий.
Текущие XLSX создаются без комментариев; актуальные проверки и ограничения —
в [REAL_IMAGES_EXCEL_CORRECTIVE_AUDIT.md](REAL_IMAGES_EXCEL_CORRECTIVE_AUDIT.md).

Исходный baseline: 2c7727e18446b810b3650ad8b2f4948a42c90d3c, v0.4,
114 тестов. Candidate остаётся PARTIAL до независимого ручного gold и
эксплуатационной проверки. Технический SUCCESS не доказывает OCR accuracy.

## Идентичность версии

Источник истины — immutable Git tag vMAJOR.MINOR на точном commit.
Локальный checkout должен иметь fetched tags (`git fetch origin --tags`);
runtime никогда не получает их по сети. Чистый tagged HEAD показывает MAJOR.MINOR;
изменённый/untagged HEAD показывает development. Frozen runtime читает только
встроенный _build_version, не запускает Git. Build проверяет SHA зарезервированного
тега перед PyInstaller. Нет version-bump commit или CI push.

hatch-vcs/setuptools-scm строит package metadata из Git. Release wheel/sdist
имеет точное MAJOR.MINOR. Внутренний PEP 440 development идентификатор содержит
ближайшую версию + hash (и дату для dirty tree); это не release и UI показывает
development. Без Git и без VCS metadata допустим 0.0.dev0, никогда 0.1.
VCS build hook сохраняет metadata при wheel-from-sdist. Отдельный тест реально
строит sdist/wheel, устанавливает wheel в изолированное окружение и проверяет
runtime и importlib.metadata. Remote reservation algorithm сохранён.

## Fidelity и публикация XLSX

Простые целые до 15 цифр и десятичные числа до 15 общих цифр конвертируются,
только если Decimal(str(float)) равен исходному Decimal. Decimal precision
сохраняется форматом `0.00` и т.п. Leading zeros, scientific notation, dates,
коды, +prefix и negative zero сохраняются строками. Все OCR strings принудительно
имеют type s, в том числе review warnings. Исходный canonical OCR text хранится
в комментарии каждой ячейки; это часть пользовательского результата, не лог.
Разделитель Excel зависит от локали: сохраняется разрядность, исходная пунктуация
доступна в комментарии. Тесты проверяют value, type, format и восстановленный текст.

Полностью сохранённый и открытый openpyxl временный XLSX создаётся в выходном
каталоге. Перед публикацией проверяется отмена. Без overwrite нужен hardlink:
ошибка поддержки/доступа приводит к отказу с удалением temp, без copy fallback.
Существующий файл и concurrent race не перезаписываются. С overwrite применяется
os.replace; атомарность зависит от underlying filesystem, power-loss durability
не заявляется. Отмена после atomic commit не отзывает уже завершённый файл.

По [Microsoft filesystem comparison](https://learn.microsoft.com/en-us/windows/win32/fileio/filesystem-functionality-comparison)
NTFS поддерживает hardlinks, exFAT/FAT32 — нет (UNSUPPORTED exclusive publication).
[CreateHardLink](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createhardlinka)
документирует SMB3 support с исключениями continuous availability, TFO и scale-out.
Общий SMB PASS не заявляется. CI Windows проверяет runner directory, а не все ФС;
реальные FAT/exFAT/SMB и чистая Windows VM остаются PENDING.

## Immutable rerun

Existing release проверяется по tagName, exact tag SHA, published prerelease,
title, точным двум asset names, sizes, GitHub SHA256 digests и checksum содержимому.
Скачанный ZIP проверяется и его GUI/CLI реально проходят frozen smoke.
Полный matching release даёт PASS без upload; mismatch даёт FAIL без overwrite.
Отсутствующий release создаётся после checks/build/smoke и затем проверяется.
Network/auth error не считается отсутствием. Новый build ZIP не сравнивается
побайтно со старым: PyInstaller/ZIP не заявлены reproducible; проверяется
самосогласованность immutable исторического asset, версия EXE и встроенный
BUILD_COMMIT. CLI диагностика `--build-commit` и GUI smoke `--expected-commit`
проверяют принадлежность frozen binary к зарезервированному SHA.

## Local-only quality

Изображение и baseline XLSX существуют локально; приватные имена файлов опущены.
Baseline экспортирован без inference; исходный v0.4 XLSX не изменяется.
`uv run python -m localocr.quality --xlsx PATH --output .evidence/quality-v0.4`
создаёт actual.json (coordinates 1-based, spans, value type, number_format,
original text если комментарий есть), пустой manual-gold.json 35×9 и summary.
Gold нельзя заполнять OCR ответом. Оператор сверяет каждый anchor с изображением,
удаляет covered coordinates, задаёт spans/text/type и human_verified=true.
Повторный запуск с `--gold PATH` сравнивает shapes/spans, missing/extra,
text substitutions, unflagged mismatches, REVIEW count и статистику по типам.
Без полного human gold — QUALITY_PENDING, никаких процентов.
В v0.4 original OCR text для чисел отсутствует; это явно учитывается сравнением.
Regression использует тот же canonical input восстановленный из локального
baseline, без новых тяжёлых inference; это writer regression, не новая OCR validation.
Synthetic правильная геометрия с неверным текстом демонстрирует unflagged mismatch.

Local quality JSON/CSV, изображения, OCR ответы и пользовательские XLSX запрещены
в Git/release/handoff. Переносимый handoff содержит только source snapshot,
JUnit, public diagnostic counts, CI/release metadata и unresolved issues.

## Проверки и пределы

Python 3.14, PEP 758 `except A, B:` сохранён. GUI и общий service сохранены.
Runtime httpx: trust_env=False, follow_redirects=False, verify=True,
connect=5, общий deadline, local/LAN URL validation и тесты external sockets.
Реальный отдельный Ollama/LAN HTTPS и чистая Windows VM — PENDING.
Окончательные SHA, checks, jobs и release evidence записываются после push
в локальный переносимый handoff; этот документ не предрешает CI результат.

## Исправление окружения reserve после первого push

Первый корректирующий SHA 662c9bb остановился в reserve: системный Python runner
не поддерживает PEP 758 при импорте нового __init__. Проверки Linux/Windows
под Python 3.14 прошли. Валидный синтаксис не изменён: reserve теперь явно
устанавливает и запускает Python 3.14 через uv --no-project до checks/build.
v0.5 зарезервирован исходным алгоритмом за 662c9bb; повтор локально переиспользовал
ту же reservation. Необходимый дополнительный main push потребляет v0.6.
Это не version-bump commit; история и v0.4 не изменены.

Windows v0.6 build и GUI/CLI frozen smoke прошли. Release verification безопасно
отказала до create: GitHub API Unicode JSON декодировался по Windows cp1252.
Ввод GitHub subprocess и локального Git теперь явно UTF-8. Mock контракт
с Unicode API JSON проверяет отсутствие release отдельно от сетевой ошибки.
Необходимый дополнительный push резервирует v0.7; v0.5/v0.6 tags сохраняются.

Финальная сверка контракта после успешного v0.7/rerun выявила: caller разрешал
initial create при отсутствии release и на rerun. Strict --require-existing
теперь обязателен на run_attempt > 1 и при post-create verification. Исчезнувший
historical release даёт FAIL без recreation, что проверяет mock regression.
Необходимый последний push потребляет v0.8; опубликованный v0.7 не изменяется.
