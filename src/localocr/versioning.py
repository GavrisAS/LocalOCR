"""Immutable two-component remote tag reservation, ordered by push predecessor."""

import re

TAG = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def parse_tag(tag: str) -> tuple[int, int] | None:
    match = TAG.fullmatch(tag)
    return (int(match.group(1)), int(match.group(2))) if match else None


def select_tag(tags: dict[str, str], sha: str, before: str, major: int) -> str | None:
    valid = {name: commit for name, commit in tags.items() if parse_tag(name) is not None}
    existing = [name for name, commit in valid.items() if commit == sha]
    if len(existing) > 1:
        raise ValueError("Multiple reservations for one SHA")
    if existing:
        return existing[0]
    if before != "0" * 40 and before not in valid.values():
        return None  # predecessor push has not reserved yet; never approximate
    if before != "0" * 40 and valid:
        latest = max(valid, key=lambda name: parse_tag(name) or (-1, -1))
        if valid[latest] != before:
            raise ValueError("Remote reservations do not follow the push predecessor")
    versions = [parse_tag(name) for name in valid]
    if any(version and version[0] > major for version in versions):
        raise ValueError("Major downgrade prohibited")
    minors = [version[1] for version in versions if version and version[0] == major]
    return f"v{major}.{max(minors, default=0) + 1}"
