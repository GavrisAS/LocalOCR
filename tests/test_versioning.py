import pytest

from localocr.versioning import parse_tag, select_tag

ZERO = "0" * 40


def test_first_push_and_rerun_failed_build():
    assert select_tag({}, "first", ZERO, 0) == "v0.1"
    reserved = {"v0.1": "first"}
    assert select_tag(reserved, "first", ZERO, 0) == "v0.1"
    assert select_tag(reserved, "second", "first", 0) == "v0.2"


def test_close_push_order_and_collision():
    assert select_tag({}, "second", "first", 0) is None
    assert select_tag({"v0.1": "other"}, "second", "first", 0) is None
    assert select_tag({"v0.1": "first"}, "second", "first", 0) == "v0.2"
    assert select_tag({"v0.1": "first", "v0.2": "second"}, "second", "first", 0) == "v0.2"
    with pytest.raises(ValueError):
        select_tag({"v0.1": "same", "v0.2": "same"}, "same", ZERO, 0)


def test_numeric_major():
    tags = {"v0.9": "nine", "v0.10": "ten", "v4.1.0": "unrelated", "blah": "other"}
    assert select_tag(tags, "eleven", "ten", 0) == "v0.11"
    assert select_tag(tags, "major", "ten", 1) == "v1.1"
    with pytest.raises(ValueError):
        select_tag({"v1.1": "one"}, "two", "one", 0)


@pytest.mark.parametrize("tag", ["v0.1.0", "v0.01", "0.1", "latest", "v-1.1", "v1.a"])
def test_invalid_tags(tag):
    assert parse_tag(tag) is None


def test_remote_collision_cannot_skip_version():
    with pytest.raises(ValueError, match="predecessor"):
        select_tag({"v0.1": "first", "v0.2": "unexpected"}, "second", "first", 0)
