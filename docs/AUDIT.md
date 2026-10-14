# Аудит первого candidate

Дата: 2026-10-14. Локальный Python 3.14.8, locked dependencies.

| Проверка | Фактический результат перед первым push |
|---|---|
| Ruff check / format | PASS |
| ty | PASS |
| pytest | PASS, 114 тестов |
| Offline с запретом внешних socket.connect | PASS, локальный HTTP mock + XLSX |
| Qt event loop, worker, отмена, настройки | PASS, offscreen Linux |
| Реальный Ollama doctor | PASS, glm-ocr:latest |
| Пользовательское изображение end-to-end | PASS технический конвейер, результат REVIEW; 35×9, 11 merges, один конфликт |
| Синтетическая таблица, реальная GLM-OCR | PASS, SUCCESS; roundtrip 2×2 с проверкой значений |
| Независимая текстовая/структурная точность | PENDING, нет эталона |
| Linux/Windows GitHub CI | PASS для 0460f9e, 70f1198, 61caa6d; финальный commit должен пройти CI |
| Windows frozen smoke / ZIP | FAIL для v0.1: UTF-8 console output; исправлено, повторная сборка PENDING |
| LAN HTTP через частный IP интерфейса с запретом других sockets | PASS, local mock + XLSX |
| Отдельный LAN сервер / HTTPS deployment | PENDING |

Отчёты pytest и пользовательская диагностика остаются локальными в .evidence
и не коммитятся. Сырые изображения/ответы/результаты прототипа исключены Git.

Содержательные тесты включают синтетическую геометрию 2×2, 3×5, 9×32,
12×50, 50×12 в разных масштабах, 50-строчную фрагментную сборку, Unicode,
spans, пустые ячейки, формулы, переименование, batch errors, реальные git
remote reservations. Mock-тесты не доказывают точность модели.

Candidate не объявляется production-ready. Конфликты на границах OCR частей
отклоняются, слабая геометрия — REVIEW; это намеренная защита от ложного успеха.

Первый push зарезервировал v0.1 до проверок. Windows GUI smoke прошёл,
CLI smoke выявил кодировку консольного вывода; Release v0.1 не опубликован.
Следующий push должен получить v0.2, не переписывая v0.1.

Ранняя реальная проверка вернула HTTP 500 при повторной генерации HTML.
После ограничения остановки для одиночной геометрической таблицы synthetic
SUCCESS. На пользовательской таблице partial header separator обнаруживается
общим алгоритмом; повторная проверка конфликтующего текста не даёт независимого
эталона, поэтому результат REVIEW. Нет заявленного процента точности.

Финальный аудит дополнительно проверяет отсутствие исполняемых формул на
листе «Проверка» (включая warning strings), UTF-8 launcher, русский GUI summary.
Linux source GUI smoke фактически запущен с Qt offscreen, PASS.
Финальные remote CI/release результаты фиксируются в отчёте handoff после
завершения runner; текущий документ не выдаёт pending сборку за PASS.
