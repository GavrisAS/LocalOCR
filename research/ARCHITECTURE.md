# Stage 1: контракт независимой геометрии (проект, не production)

Production service не изменён. Этот документ задаёт проверяемый контракт будущего
адаптера; наличие документа не означает реализованную поддержку.

`TableRegion → OrientationCandidate → CellGeometry → TextBox/Observation → Alignment → CanonicalTable`

* TableRegion: original image SHA256, original width/height, original polygon,
  detector identity/revision, region identifier. Никакого OCR в identity.
* OrientationCandidate: angle 0/90/180/270, skew, source→working affine 3×3 и inverse,
  working dimensions, orientation evidence. Четыре гипотезы не означают четыре LLM
  запроса: сначала независимый detector/orientation classifier, затем выбор или ambiguity.
* CellGeometry: source-grid row/column, rowspan/colspan, original polygon,
  hypothesis identifier и evidence detector/line/structure. Row в HTML хранится
  отдельным полем и не является source-grid row. Линии — evidence, не gate.
* TextBox: original polygon, независимый detector score/identity. Observation:
  verbatim text, recognizer identity, region, request identifier, inference fingerprint.
  Detector score не является вероятностью правильности текста.
* Alignment: overlap containment/IoU и допустимые альтернативы; one-to-many
  (несколько строк в одной ячейке), many-to-one merge и неоднозначность явно.
  Нет deduplication по тексту, выдуманных пустых td и компенсационных сдвигов.
* CanonicalTable допускается только после проверки bounds/overlaps/spans. Для
  неразрешённого geometry agreement сохраняются гипотезы и observations отдельно.

Предлагаемый machine-readable ambiguity record:

```json
{"region_id":"opaque-id","code":"MULTIPLE_CELL_ASSIGNMENTS",
 "observation_id":"opaque-id","candidate_cell_ids":["a","b"],
 "geometry_state":"ambiguous","structural_completeness":"unknown",
 "content_evidence":"single-recognizer","human_verified":false}
```

Structural completeness, content evidence и human_verified — три независимых поля.
Ни HTML, ни detector score не устанавливают human_verified. Неустановленная
геометрия должна экспортироваться на лист «Непривязанные OCR-наблюдения»; PARTIAL
и REVIEW сохраняют предупреждения. До Stage 1 PASS этот контракт в writer не вносится.

Региональный GLM допускается только после diagnostic reason (например, несколько
text boxes без распознавания в одном подтверждённом cell polygon), при положительном
remaining budget и без увеличения установленного max_calls. Бюджет включает все
transport attempts. Жёсткий deadline реализуется на внешнем процессе: проверка
времени лишь перед запросом не ограничивает уже начатый запрос.

Будущий cache fingerprint: source bytes, normalization version, algorithm version,
model weights hashes/revisions, layout/text pipeline configs, inference parameters,
server version, runner/build identity, backend/device and qualification epoch.
Unknown runner identity → cache equivalence unproven. Явный requalify/epoch должен
запрещать reuse старого качества. Сейчас production требует overwrite после server
update; это ограничение остаётся, изменения отложены до Stage 2.

Для ориентационной квалификации нужны независимые original-image polygons для
каждой ячейки после rotation/expand/skew. Legacy synthetic generator сохраняет
pre-rotation boxes; его HTML-index metric не квалифицирует обратную геометрию.
Новый holdout нельзя считать пройденным по одному совпадению текстов и HTML rows.
