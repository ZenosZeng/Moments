import json

import pytest

from pic_timeline.local_cache import JsonCache, export_lock, fingerprint, jpeg_cache_path, valid_preview_entry


def test_json_cache_persists_and_rejects_stale_version_or_corruption(tmp_path):
    cache = JsonCache(tmp_path / "cache", 1)
    signature = fingerprint({"city": "example", "photos": [1]})
    cache.save("2024-01-01", signature, {"value": 1})
    assert JsonCache(cache.root, 1).load("2024-01-01", signature) == {"value": 1}
    assert cache.load("2024-01-01", fingerprint({"changed": True})) is None
    assert JsonCache(cache.root, 2).load("2024-01-01", signature) is None
    file = next(cache.root.glob("*.json"))
    file.write_text("{broken", encoding="utf-8")
    assert cache.load("2024-01-01", signature) is None
    file.write_text(json.dumps([1, 2]), encoding="utf-8")
    assert cache.load("2024-01-01", signature) is None


def test_cache_keys_do_not_change_when_original_root_is_renamed(tmp_path):
    record = {"size": 10, "mtime_ns": 20, "source_root": "before-rename"}
    first = jpeg_cache_path(tmp_path, "phone/month/photo.jpg", record, "preview-v1")
    assert first == jpeg_cache_path(tmp_path, "phone/month/photo.jpg", {**record, "source_root": "after-rename"}, "preview-v1")
    assert first != jpeg_cache_path(tmp_path, "phone/month/photo.jpg", {**record, "mtime_ns": 21}, "preview-v1")
    assert first != jpeg_cache_path(tmp_path, "phone/month/photo.jpg", {**record, "size": 11}, "preview-v1")
    assert first != jpeg_cache_path(tmp_path, "phone/month/photo.jpg", record, "thumbnail-v1")


def test_preview_cache_rejects_private_or_unknown_fields():
    empty = {"trip": None, "warnings": [], "paths": [], "cityKeys": [], "countryCodes": []}
    assert valid_preview_entry(empty)
    assert not valid_preview_entry({**empty, "people": []})
    assert not valid_preview_entry({**empty, "warnings": [123]})


def test_export_lock_blocks_another_export_and_releases_cleanly(tmp_path):
    with export_lock(tmp_path):
        with pytest.raises(ValueError, match="另一个公开导出"):
            with export_lock(tmp_path):
                raise AssertionError("must not enter")
    with export_lock(tmp_path):
        pass
