"""Canonical, independent table model and strict grid validation."""

from dataclasses import dataclass, field


class StructureError(ValueError):
    pass


@dataclass
class ValidationIssue:
    code: str
    message: str
    row: int | None = None
    column: int | None = None


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
