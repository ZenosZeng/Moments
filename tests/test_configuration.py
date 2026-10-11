from pathlib import Path

import pytest

from pic_timeline.analysis import find_source_root
from pic_timeline.web import build_parser


def test_source_can_be_configured_without_personal_defaults(tmp_path, monkeypatch):
    source = tmp_path / "archive"
    source.mkdir()
    monkeypatch.setenv("MOMENTS_SOURCE", str(source))
    assert find_source_root() == source.resolve()


def test_configured_missing_source_is_not_silently_replaced(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMENTS_SOURCE", str(tmp_path / "missing"))
    with pytest.raises(FileNotFoundError, match="Source directory"):
        find_source_root()


def test_explicit_search_does_not_use_environment(tmp_path, monkeypatch):
    source = tmp_path / "photos archive"
    source.mkdir()
    monkeypatch.setenv("MOMENTS_SOURCE", str(tmp_path / "missing"))
    assert find_source_root(tmp_path, "photos") == source.resolve()


def test_app_accepts_explicit_source():
    assert build_parser().parse_args(["--source", "archive"]).source == Path("archive")
