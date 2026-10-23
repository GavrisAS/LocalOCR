"""Protect the pilot's scoring geometry; these tests do not qualify OCR accuracy."""

import math
import runpy
from pathlib import Path

import pytest

SCORING = runpy.run_path(str(Path(__file__).parents[1] / "research/score_paddle.py"))
METRICS = runpy.run_path(str(Path(__file__).parents[1] / "research/summarize_pilot.py"))


@pytest.mark.parametrize("angle", [0, 90, 180, 270, 2, 92])
def test_original_polygon_rotation_inverse(angle):
    original = [(10, 20), (110, 20), (110, 70), (10, 70)]
    size = (240, 130)
    cos, sin = abs(math.cos(math.radians(angle))), abs(math.sin(math.radians(angle)))
    output = (math.ceil(size[1] * sin + size[0] * cos), math.ceil(size[1] * cos + size[0] * sin))
    rotated = SCORING["rotate"](original, angle, size, output)
    restored = SCORING["rotate"](rotated, -angle, output, size)
    for actual, expected in zip(restored, original, strict=True):
        assert actual == pytest.approx(expected, abs=1e-9)
    assert SCORING["iou"](restored, original) == pytest.approx(1)


def test_polygon_overlap_does_not_reward_disjoint_cells():
    left = [(0, 0), (10, 0), (10, 10), (0, 10)]
    right = [(20, 0), (30, 0), (30, 10), (20, 10)]
    assert SCORING["iou"](left, right) == 0


def test_cer_counts_deletions_and_cyrillic_substitution():
    assert METRICS["distance"]("Сумма", "Сума") == 1
    assert METRICS["distance"]("12,05", "") == 5


def test_unresolved_blank_is_not_scored_as_recognized_empty(tmp_path):
    import json

    (tmp_path / "private-results.json").write_text(
        json.dumps([{"case": "CASE-01", "status": "PARTIAL", "seconds": 1, "requests": []}])
    )
    case = tmp_path / "CASE-01"
    case.mkdir()
    cell = {"row": 0, "column": 0, "rowspan": 1, "colspan": 1, "text": "", "header": True}
    (case / "observations.json").write_text(
        json.dumps(
            {
                "tables": [
                    {
                        "rows": 1,
                        "columns": 1,
                        "cells": [{**cell, "provenance": {"state": "unresolved"}}],
                    }
                ]
            }
        )
    )
    gold = tmp_path / "gold.json"
    gold.write_text(
        json.dumps(
            [{"style": "grid", "rotation": 0, "gold": {"rows": 1, "columns": 1, "cells": [cell]}}]
        )
    )
    result = METRICS["summarize"](tmp_path, gold)["cases"][0]
    assert result["exact_text_position_span"] == 0
    assert not result["full_table_match"]
    assert result["unresolved_positions_in_hypothesis"] == 1
