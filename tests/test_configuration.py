from pathlib import Path

import pytest
import yaml

from pic_timeline.analysis import find_source_root
from pic_timeline.web import build_parser
from pic_timeline.configuration import load_config


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


def _config(root, content):
    (root / "config").mkdir(parents=True, exist_ok=True)
    if isinstance(content, dict):
        content = yaml.safe_dump(content, sort_keys=False)
    (root / "config" / "local.yaml").write_text(content, encoding="utf-8")
    return load_config(root)


def test_local_config_resolves_multiple_sources_and_relative_storage(tmp_path, monkeypatch):
    first = tmp_path / "photos-old"
    second = tmp_path / "photos-new-2026"
    first.mkdir()
    second.mkdir()
    root = tmp_path / "Moments"
    config = _config(root, {
        "photos": {"sources": [
            {"id": "old", "path": first.as_posix(), "legacy_paths": True},
            {"id": "new", "parent": tmp_path.as_posix(), "prefix": "photos-new"},
        ]},
        "app": {"port": 8888},
        "publish": {"base_path": "/example/"},
    })
    monkeypatch.setenv("MOMENTS_SOURCE", str(tmp_path / "not-configured"))
    monkeypatch.chdir(first)
    assert [s.root for s in config.resolve_sources()] == [first, second]
    assert config.index == root / "data" / "db" / "photo_index.sqlite3"
    assert config.port == 8888
    assert config.base_path == "/example/"
    assert [source.legacy_paths for source in config.sources] == [True, False]


@pytest.mark.parametrize("settings", [
    {"app": {"port": "8765"}}, {"app": {"port": True}}, {"app": {"port": 65536}},
    {"app": {"host": "0.0.0.0"}}, {"app": {"prot": 8765}},
    {"storage": {"exports": "data"}}, {"storage": {"annotations": "../old/annotations.sqlite3"}},
    {"storage": {"thumbnails": "data/exports/cache"}},
    {"publish": {"base_path": "https://example.com/"}}, {"publish": {"base_path": "/../"}},
])
def test_invalid_or_unsafe_settings_are_rejected(tmp_path, settings):
    with pytest.raises(ValueError):
        _config(tmp_path / "Moments", {
            "photos": {"sources": [{"id": "archive", "path": "../photos"}]},
            **settings,
        })


def test_config_requires_unique_stable_ids_and_unambiguous_roots(tmp_path):
    with pytest.raises(ValueError, match="id"):
        _config(tmp_path / "Moments", {"photos": {"sources": [
            {"id": "same", "path": "../a"}, {"id": "same", "path": "../b"},
        ]}})
    for name in ("archive-a", "archive-b"):
        (tmp_path / name).mkdir()
    config = _config(tmp_path / "Moments", {"photos": {"sources": [
        {"id": "archive", "parent": tmp_path.as_posix(), "prefix": "archive-"},
    ]}})
    with pytest.raises(ValueError, match="2"):
        config.resolve_sources()


def test_config_rejects_overlapping_roots_and_photos_inside_repository(tmp_path):
    parent = tmp_path / "photos"
    child = parent / "child"
    child.mkdir(parents=True)
    root = tmp_path / "Moments"
    config = _config(root, {"photos": {"sources": [
        {"id": "parent", "path": parent.as_posix()},
        {"id": "child", "path": child.as_posix()},
    ]}})
    with pytest.raises(ValueError, match="互相包含"):
        config.resolve_sources()
    config = _config(root, {"photos": {"sources": [{"id": "inside", "path": "."}]}})
    with pytest.raises(ValueError, match="仓库外"):
        config.resolve_sources()


def test_missing_private_config_has_one_time_setup_instructions(tmp_path):
    with pytest.raises(FileNotFoundError, match="Copy-Item"):
        load_config(tmp_path)


@pytest.mark.parametrize("path", ["../compositions", "data", "data/exports/drafts", "data/cache/thumbnails/drafts", "data/backups/drafts", "data/db"])
def test_composition_storage_is_private_and_separate(tmp_path, path):
    with pytest.raises(ValueError):
        _config(tmp_path / "Moments", {"photos": {"sources": [{"id": "archive", "path": "../photos"}]}, "storage": {"compositions": path}})


def test_composition_storage_default_needs_no_config_migration(tmp_path):
    root = tmp_path / "Moments"
    config = _config(root, {"photos": {"sources": [{"id": "archive", "path": "../photos"}]}})
    assert config.compositions == root / "data/compositions"


@pytest.mark.parametrize("content", [
    "",
    "[]",
    "photos: [",
    "app:\n  port: 8765\n  port: 8000\n",
    "app: {}\napp: {}\n",
    "1: value\n",
    "app: !!python/object:builtins.object {}\n",
])
def test_yaml_rejects_invalid_shapes_duplicate_keys_and_unsafe_tags(tmp_path, content):
    with pytest.raises(ValueError, match="local.yaml"):
        _config(tmp_path / "Moments", content)


def test_yaml_syntax_error_reports_line_without_echoing_private_values(tmp_path):
    with pytest.raises(ValueError) as error:
        _config(tmp_path / "Moments", 'photos:\n  sources: ["private-value"\n')
    assert "第 3 行" in str(error.value)
    assert "private-value" not in str(error.value)


def test_yaml_requires_boolean_legacy_paths(tmp_path):
    with pytest.raises(ValueError, match="legacy_paths"):
        _config(tmp_path / "Moments", {"photos": {"sources": [
            {"id": "archive", "path": "../photos", "legacy_paths": "true"},
        ]}})
