# Аудит первого candidate

Дата: 2026-10-14. Локальный Python 3.14.8, locked dependencies.

| Проверка | Фактический результат перед первым push |
|---|---|
| Ruff check / format | PASS |
| ty | PASS |
| pytest | PASS, 104 теста |
| Offline с запретом внешних socket.connect | PASS, локальный HTTP mock + XLSX |
| Qt event loop, worker, отмена, настройки | PASS, offscreen Linux |
| Реальный Ollama doctor | PASS, glm-ocr:latest |
| Пользовательское изображение end-to-end | FAIL, Ollama HTTP 500, XLSX не создан |
| Независимая текстовая/структурная точность | PENDING, нет эталона |
| Linux/Windows GitHub CI | PENDING до публикации |
| Windows frozen smoke / ZIP | PENDING до runner |
| Реальная LAN/HTTPS установка | PENDING |

Отчёты pytest и пользовательская диагностика остаются локальными в .evidence
и не коммитятся. Сырые изображения/ответы/результаты прототипа исключены Git.

Содержательные тесты включают синтетическую геометрию 2×2, 3×5, 9×32,
12×50, 50×12 в разных масштабах, 50-строчную фрагментную сборку, Unicode,
spans, пустые ячейки, формулы, переименование, batch errors, реальные git
remote reservations. Mock-тесты не доказывают точность модели.

Candidate не объявляется production-ready. Конфликты на границах OCR частей
отклоняются, слабая геометрия — REVIEW; это намеренная защита от ложного успеха.
