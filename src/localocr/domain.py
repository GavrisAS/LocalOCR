"""Canonical, independent table model and strict grid validation."""

from dataclasses import dataclass, field

PIPELINE_VERSION = "evidence-grid-1"


class StructureError(ValueError):
    pass


@dataclass
class ValidationIssue:
    code: str
    message: str
    row: int | None = None
    column: int | None = None
    source_region: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class Evidence:
    kind: str
    region: tuple[int, int, int, int] | None = None
    observation: int | None = None
    detail: str = ""


@dataclass
class CellProvenance:
    # Evidence categories, never a fabricated model probability.
    state: str = "unverified"
    evidence: list[Evidence] = field(default_factory=list)
    coordinate_space: str = "normalized-image"
    source_polygon: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class TextObservation:
    region: tuple[int, int, int, int]
    request: int
    task: str
    text: str


@dataclass
class GridHypothesis:
    region: tuple[int, int, int, int]
    xs: list[int]
    ys: list[int]
    horizontal_support: list[list[float]]
    vertical_support: list[list[float]]
    scale_stable: bool
    source: str = "line-segments"

    def encloses(self, row: int, column: int, rowspan=1, colspan=1) -> bool:
        """Four independently observed sides; missing lines alone never imply a merge."""
        return all(
            support >= 0.7
            for support in [
                *self.horizontal_support[row][column : column + colspan],
                *self.horizontal_support[row + rowspan][column : column + colspan],
                *(self.vertical_support[r][column] for r in range(row, row + rowspan)),
                *(self.vertical_support[r][column + colspan] for r in range(row, row + rowspan)),
            ]
        )

    def supports_span(self, row: int, column: int, rowspan: int, colspan: int) -> bool:
        if not self.encloses(row, column, rowspan, colspan):
            return False
        # OCR span + observed enclosure + no supported internal rule. Ambiguous
        # broken rules are unresolved; an absent rule on its own proves nothing.
        internal = [
            self.horizontal_support[r][c]
            for r in range(row + 1, row + rowspan)
            for c in range(column, column + colspan)
        ] + [
            self.vertical_support[r][c]
            for r in range(row, row + rowspan)
            for c in range(column + 1, column + colspan)
        ]
        return all(support <= 0.1 for support in internal)


@dataclass
class Cell:
    row: int
    column: int
    text: str
    rowspan: int = 1
    colspan: int = 1
    is_header: bool = False
    source_region: tuple[int, int, int, int] | None = None
    warnings: list[str] = field(default_factory=list)
    provenance: CellProvenance = field(default_factory=CellProvenance)


@dataclass
class CellObservation:
    cell: Cell
    fragment_region: tuple[int, int, int, int]


@dataclass
class Table:
    cells: list[Cell]
    rows: int
    columns: int
    issues: list[ValidationIssue] = field(default_factory=list)
    row_heights: list[float] = field(default_factory=list)
    column_widths: list[float] = field(default_factory=list)

    def grid(self) -> dict[tuple[int, int], Cell]:
        if not 1 <= self.rows <= 10000 or not 1 <= self.columns <= 1000:
            raise StructureError("Размер таблицы вне допустимых границ")
        if self.rows * self.columns > 100000:
            raise StructureError("Таблица превышает 100000 ячеек")
        occupied: dict[tuple[int, int], Cell] = {}
        for cell in self.cells:
            if cell.row < 0 or cell.column < 0 or cell.rowspan < 1 or cell.colspan < 1:
                raise StructureError("Некорректные координаты или spans")
            if cell.row + cell.rowspan > self.rows or cell.column + cell.colspan > self.columns:
                raise StructureError("Объединение выходит за границы таблицы")
            for row in range(cell.row, cell.row + cell.rowspan):
                for column in range(cell.column, cell.column + cell.colspan):
                    key = (row, column)
                    if key in occupied:
                        raise StructureError("Перекрытие ячеек")
                    occupied[key] = cell
        if len(occupied) != self.rows * self.columns:
            raise StructureError("Пропуски или неоднозначное количество столбцов")
        return occupied


@dataclass
class TableDocument:
    tables: list[Table]
    issues: list[ValidationIssue] = field(default_factory=list)
    normalization: dict = field(default_factory=dict)

    def outcome(self) -> dict:
        cells = [cell for table in self.tables for cell in table.cells]
        recognized = sum(bool(c.text.strip()) and c.provenance.state != "unresolved" for c in cells)
        verified = sum(bool(c.text.strip()) and c.provenance.state == "corroborated" for c in cells)
        unresolved = sum(c.provenance.state == "unresolved" for c in cells)
        unresolved += len(self.issues)
        unverified = recognized - verified
        warnings = any(t.issues or any(c.warnings for c in t.cells) for t in self.tables)
        return {
            "status": "FAILED"
            if not recognized
            else ("PARTIAL" if unresolved else "REVIEW" if unverified or warnings else "SUCCESS"),
            "recognized_anchors": recognized,
            "verified_anchors": verified,
            "unresolved_anchors": sum(c.provenance.state == "unresolved" for c in cells),
            "unresolved_regions": unresolved,
            "unverified_content": unverified,
        }

    def validate(self) -> None:
        if not self.tables:
            raise StructureError("Таблицы не найдены")
        for table in self.tables:
            table.grid()


@dataclass
class JobResult:
    source: str
    status: str
    output: str | None = None
    message: str = ""
    seconds: float = 0
    tables: int = 0
    shapes: list[tuple[int, int]] = field(default_factory=list)
    warnings: int = 0
    recognized_anchors: int = 0
    verified_anchors: int = 0
    unresolved_anchors: int = 0
    unresolved_regions: int = 0
    unverified_content: int = 0
    calls: int = 0
    http_attempts: int = 0
    resumed: bool = False
    stage_seconds: dict[str, float] = field(default_factory=dict)
