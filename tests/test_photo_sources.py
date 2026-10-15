import json
import os
import sqlite3
from pathlib import Path

import pytest
from PIL import Image

from pic_timeline.analysis import scan_archive, scan_sources
from pic_timeline.export_public import export_public, ExportStats
from pic_timeline.photo_sources import PhotoSource, bind_index_sources, register_sources, resolve_photo_path
from pic_timeline.web import PhotoIndex, create_app


def _photo(root: Path, name="same.jpg", capture="2024:01:05 12:00:00"):
    path = root / "202401_a" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    exif = Image.Exif()
    exif[36867] = capture
    Image.new("RGB", (12, 8), "green").save(path, exif=exif)
    return path


def _metadata(index):
    with sqlite3.connect(index) as connection:
        return dict(connection.execute("SELECT key,value FROM metadata"))


def test_same_file_names_from_two_sources_merge_counts_without_collision(tmp_path):
    roots = [tmp_path / "old", tmp_path / "new"]
    paths = [_photo(root) for root in roots]
    stamps = [p.stat().st_mtime_ns for p in paths]
    sources = [PhotoSource(name, root) for name, root in zip(("old", "new"), roots)]
    index = tmp_path / "index.sqlite3"
    records, months, counters = scan_sources(sources, index)
    assert {r.relative_path for r in records} == {"old/202401_a/same.jpg", "new/202401_a/same.jpg"}
    assert months == ["202401"]
    assert counters["scanned"] == 2
    assert PhotoIndex(index).overview_counts("2024-01") == {"2024-01-05": 2}
    assert [resolve_photo_path(_metadata(index), r.relative_path) for r in records] == paths
    assert [p.stat().st_mtime_ns for p in paths] == stamps


def test_renames_and_reordering_keep_keys_and_caches(tmp_path):
    first, second = tmp_path / "old", tmp_path / "new"
    _photo(first)
    _photo(second)
    index = tmp_path / "index.sqlite3"
    records, _, _ = scan_sources([PhotoSource("one", first), PhotoSource("two", second)], index)
    renamed = tmp_path / "renamed"
    first.rename(renamed)
    sources = [PhotoSource("two", second), PhotoSource("one", renamed)]
    bind_index_sources(index, sources)
    assert resolve_photo_path(_metadata(index), "one/202401_a/same.jpg").is_file()
    refreshed, _, counters = scan_sources(sources, index)
    assert counters["cached"] == 2
    assert {r.relative_path for r in refreshed} == {r.relative_path for r in records}


def test_legacy_keys_survive_migration_and_new_source_collisions(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    _photo(old)
    _photo(new)
    index = tmp_path / "index.sqlite3"
    scan_archive(old, index)
    sources = [PhotoSource("old", old, legacy_paths=True), PhotoSource("new", new)]
    with sqlite3.connect(index) as connection:
        register_sources(connection, sources, legacy_source_id="old")
    records, _, counters = scan_sources(sources, index)
    assert {r.relative_path for r in records} == {"202401_a/same.jpg", "new/202401_a/same.jpg"}
    assert counters["cached"] == 1
    assert resolve_photo_path(_metadata(index), "202401_a/same.jpg") == old / "202401_a" / "same.jpg"
    rebuilt = tmp_path / "rebuilt-index.sqlite3"
    rebuilt_records, _, _ = scan_sources(list(reversed(sources)), rebuilt)
    assert {r.relative_path for r in rebuilt_records} == {r.relative_path for r in records}


def test_legacy_namespace_setting_cannot_be_changed(tmp_path):
    root = tmp_path / "photos"
    _photo(root)
    index = tmp_path / "index.sqlite3"
    scan_sources([PhotoSource("archive", root, legacy_paths=True)], index)
    with pytest.raises(ValueError, match="不可修改"):
        bind_index_sources(index, [PhotoSource("archive", root)])


def test_disabling_source_does_not_delete_its_index_or_change_namespace(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    _photo(old)
    _photo(new)
    index = tmp_path / "index.sqlite3"
    scan_sources([PhotoSource("old", old), PhotoSource("new", new)], index)
    scan_sources([PhotoSource("new", new)], index)
    assert PhotoIndex(index).totals()["photos"] == 2


@pytest.mark.parametrize("key", ["old/../outside.jpg", "old/C:/outside.jpg", "/outside.jpg"])
def test_multi_source_paths_cannot_escape_roots(tmp_path, key):
    metadata = {"photo_sources": json.dumps({"old": {"root": str(tmp_path), "prefix": "old/"}})}
    with pytest.raises(ValueError):
        resolve_photo_path(metadata, key)


def test_multi_source_progress_counts_all_files_and_cached_records(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    _photo(old)
    _photo(new)
    sources = [PhotoSource("old", old), PhotoSource("new", new)]
    events = []
    progress = lambda stage, completed, total: events.append((stage, completed, total))
    index = tmp_path / "progress-index.sqlite3"
    records, _, _ = scan_sources(sources, index, progress=progress)
    assert len(records) == 2
    assert [event for event in events if event[0] == "读取拍摄日期"] == [
        ("读取拍摄日期", 0, 2), ("读取拍摄日期", 1, 2), ("读取拍摄日期", 2, 2),
    ]
    assert events[-1] == ("整理索引", 1, 1)
    events.clear()
    reports = []
    _, _, counters = scan_sources(sources, index, progress=progress, cache_report=lambda *report: reports.append(report))
    assert counters["cached"] == 2
    assert ("读取拍摄日期", 0, 0) in events
    assert reports == [(2, 2, "张照片")]


def test_unchanged_index_skips_exif_and_only_reads_new_or_changed_files(tmp_path, monkeypatch):
    from pic_timeline import analysis

    root = tmp_path / "photos"
    original_photo = _photo(root)
    sources = [PhotoSource("phone", root)]
    index = tmp_path / "incremental.sqlite3"
    scan_sources(sources, index)
    original = analysis.extract_capture_time
    calls = []

    def capture(path):
        calls.append(path.name)
        return original(path)

    monkeypatch.setattr(analysis, "extract_capture_time", capture)
    _, _, counters = scan_sources(sources, index)
    assert not calls and counters["cached"] == 1
    _photo(root, name="new.jpg")
    _, _, counters = scan_sources(sources, index)
    assert calls == ["new.jpg"] and counters["cached"] == 1 and counters["scanned"] == 1
    calls.clear()
    before = original_photo.stat()
    _photo(root, capture="2024:01:06 12:00:00")
    os.utime(original_photo, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
    records, _, counters = scan_sources(sources, index)
    assert calls == ["same.jpg"] and counters["cached"] == 1 and counters["scanned"] == 1
    assert next(record for record in records if record.relative_path.endswith("same.jpg")).capture_date == "2024-01-06"
    calls.clear()
    (root / "202401_a" / "new.jpg").unlink()
    _, _, counters = scan_sources(sources, index)
    assert not calls and counters["removed_from_index"] == 1
    assert PhotoIndex(index).totals()["photos"] == 1


def test_failed_exif_reads_are_retried_without_changing_the_file(tmp_path, monkeypatch):
    from pic_timeline import analysis

    root = tmp_path / "photos"
    _photo(root)
    sources = [PhotoSource("phone", root)]
    index = tmp_path / "retry.sqlite3"
    original = analysis.extract_capture_time

    def fail(path):
        raise OSError("synthetic temporary read failure")

    monkeypatch.setattr(analysis, "extract_capture_time", fail)
    _, _, counters = scan_sources(sources, index)
    assert counters["errors"] == 1
    monkeypatch.setattr(analysis, "extract_capture_time", original)
    records, _, counters = scan_sources(sources, index)
    assert counters["scanned"] == 1 and counters["cached"] == 0
    assert records[0].capture_date == "2024-01-05" and not records[0].extraction_error


def test_thumbnails_and_export_use_both_sources_and_reuse_cache(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    _photo(old)
    _photo(new)
    index, annotations = tmp_path / "index.sqlite3", tmp_path / "annotations.sqlite3"
    sources = [PhotoSource("old", old), PhotoSource("new", new)]
    records, _, _ = scan_sources(sources, index)
    app = create_app(index_path=index, annotation_path=annotations, thumbnail_root=tmp_path / "cache", sources=sources)
    client = app.test_client()
    assert set(client.get("/api/overview?month=2024-01").get_json()["source_roots"]) == {str(old), str(new)}
    response = client.put("/api/days/2024-01-05/annotation", json={
        "places": [{"city": "深圳", "name": "公园"}], "isPublic": True,
        "featuredPhotos": [{"relativePath": r.relative_path} for r in records],
    })
    assert response.status_code == 200
    for record in records:
        assert client.get(f"/api/photos/{record.relative_path}/thumbnail").status_code == 200
    output = tmp_path / "public-data"
    manifest = export_public(index, annotations, output)
    assert manifest["summary"]["featuredPhotos"] == 2
    assert len({p["id"] for p in manifest["trips"][0]["photos"]}) == 2
    stats = ExportStats()
    export_public(index, annotations, output, stats=stats)
    assert stats.reused_photos == 2
    assert stats.generated_photos == 0
