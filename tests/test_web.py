from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from urllib.parse import quote

import pytest
from PIL import Image

from pic_timeline.analysis import scan_archive
from pic_timeline.export_public import (
    ConsoleProgress,
    ExportStats,
    audit_public_tree,
    export_public,
)
from pic_timeline.web import AnnotationStore, _port_is_in_use, create_app, main


def _write_jpeg(path: Path, capture_time: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (40, 30), "#287271")
    exif = Image.Exif()
    exif[36867] = capture_time
    image.save(path, exif=exif)


def _build_app(tmp_path: Path, *, local_ui_dist: Path | None = None):
    source = tmp_path / "photos test"
    _write_jpeg(source / "202405_a" / "one.jpg", "2024:05:02 10:00:00")
    _write_jpeg(source / "202405_a" / "two.jpg", "2024:05:02 11:00:00")
    _write_jpeg(source / "202405_a" / "other.jpg", "2024:05:03 09:00:00")
    missing = source / "202405_a" / "missing.png"
    Image.new("RGB", (10, 10), "white").save(missing)
    index = tmp_path / "photo-index.sqlite3"
    annotations = tmp_path / "annotations.sqlite3"
    thumbnails = tmp_path / "thumbnails"
    scan_archive(source, index, refresh=True)
    app = create_app(
        index_path=index,
        annotation_path=annotations,
        thumbnail_root=thumbnails,
        source_finder=lambda: source,
        local_ui_dist=local_ui_dist,
    )
    app.config.update(TESTING=True)
    return app, source, annotations


def test_overview_counts_only_photos_with_capture_date(tmp_path: Path) -> None:
    app, _, _ = _build_app(tmp_path)

    response = app.test_client().get("/api/overview?month=2024-05")

    assert response.status_code == 200
    payload = response.get_json()
    by_day = {item["day"]: item for item in payload["days"]}
    assert by_day[2]["count"] == 2
    assert by_day[3]["count"] == 1
    assert payload["summary"]["month_photos"] == 3
    assert payload["summary"]["included"] == 3
    assert payload["summary"]["missing"] == 1


def test_new_date_defaults_to_public(tmp_path: Path) -> None:
    app, _, _ = _build_app(tmp_path)

    payload = app.test_client().get("/api/days/2024-05-02").get_json()

    assert payload["annotation"]["annotated"] is False
    assert payload["annotation"]["isPublic"] is True


def test_default_city_setting_uses_recorded_cities_and_persists(tmp_path: Path) -> None:
    app, source, annotations_path = _build_app(tmp_path)
    client = app.test_client()

    initial = client.get("/api/settings")
    assert initial.status_code == 200
    assert initial.get_json() == {"defaultCity": "", "availableCities": []}

    for capture_date, city in (("2024-05-02", "深圳"), ("2024-05-03", "上海")):
        response = client.put(
            f"/api/days/{capture_date}/annotation",
            json={"places": [{"city": city, "name": ""}]},
        )
        assert response.status_code == 200

    rejected = client.put("/api/settings", json={"defaultCity": "北京"})
    assert rejected.status_code == 400
    assert "已有记录" in rejected.get_json()["error"]

    saved = client.put("/api/settings", json={"defaultCity": "深圳"})
    assert saved.status_code == 200
    assert saved.get_json() == {
        "defaultCity": "深圳",
        "availableCities": ["上海", "深圳"],
    }

    restarted = create_app(
        index_path=tmp_path / "photo-index.sqlite3",
        annotation_path=annotations_path,
        thumbnail_root=tmp_path / "thumbnails",
        source_finder=lambda: source,
    )
    restarted.config.update(TESTING=True)
    assert restarted.test_client().get("/api/settings").get_json()["defaultCity"] == "深圳"


def test_day_detail_returns_saved_featured_photos_before_other_photos(
    tmp_path: Path,
) -> None:
    app, _, _ = _build_app(tmp_path)
    client = app.test_client()
    assert client.put(
        "/api/days/2024-05-02/annotation",
        json={
            "places": [{"city": "深圳", "name": ""}],
            "featuredPhotos": [{"relativePath": "202405_a/two.jpg"}],
        },
    ).status_code == 200

    payload = client.get("/api/days/2024-05-02?limit=1").get_json()

    assert payload["photos"][0]["relative_path"] == "202405_a/two.jpg"
    assert payload["photos"][0]["featured"] is True


def test_annotation_persists_and_footprints_aggregate(tmp_path: Path) -> None:
    app, source, annotations_path = _build_app(tmp_path)
    client = app.test_client()
    response = client.put(
        "/api/days/2024-05-02/annotation",
        json={
            "places": ["杭州西湖", "杭州西湖"],
            "note": "春天散步",
            "reviewed": True,
        },
    )
    assert response.status_code == 200
    saved = response.get_json()
    assert [item["name"] for item in saved["places"]] == ["杭州西湖"]
    assert "people" not in saved
    assert saved["reviewed"] is True

    restarted = create_app(
        index_path=tmp_path / "photo-index.sqlite3",
        annotation_path=annotations_path,
        thumbnail_root=tmp_path / "thumbnails",
        source_finder=lambda: source,
    )
    restarted.config.update(TESTING=True)
    day = restarted.test_client().get("/api/days/2024-05-02").get_json()
    assert day["annotation"]["note"] == "春天散步"
    assert day["annotation"]["reviewed"] is True

    footprints = restarted.test_client().get("/api/footprints").get_json()["places"]
    assert len(footprints) == 1
    assert footprints[0]["date_label"] == "2024-05-02"
    assert footprints[0]["city"] == ""
    assert footprints[0]["places"] == ["杭州西湖"]
    assert footprints[0]["photo_count"] == 2


def test_footprints_merge_adjacent_days_in_the_same_city_and_sort_descending(
    tmp_path: Path,
) -> None:
    app, _, _ = _build_app(tmp_path)
    client = app.test_client()
    for capture_date, place, photo in (
        ("2024-05-02", "人才公园", "202405_a/one.jpg"),
        ("2024-05-03", "莲花山", "202405_a/other.jpg"),
    ):
        assert client.put(
            f"/api/days/{capture_date}/annotation",
            json={
                "places": [{"city": "深圳", "name": place}],
                "featuredPhotos": [{"relativePath": photo}],
                "isPublic": True,
            },
        ).status_code == 200

    journeys = client.get("/api/footprints").get_json()["places"]

    assert len(journeys) == 1
    assert journeys[0]["date_label"] == "2024-05-02 至 2024-05-03"
    assert journeys[0]["city"] == "深圳"
    assert journeys[0]["places"] == ["人才公园", "莲花山"]
    assert "people" not in journeys[0]
    assert journeys[0]["photo_count"] == 3


def test_footprints_sort_separate_journeys_by_latest_date(tmp_path: Path) -> None:
    app, _, _ = _build_app(tmp_path)
    client = app.test_client()
    for capture_date, city in (("2024-05-02", "深圳"), ("2024-05-03", "广州")):
        assert client.put(
            f"/api/days/{capture_date}/annotation",
            json={"places": [{"city": city, "name": ""}]},
        ).status_code == 200

    journeys = client.get("/api/footprints").get_json()["places"]

    assert [journey["city"] for journey in journeys] == ["广州", "深圳"]
    assert [journey["date_label"] for journey in journeys] == [
        "2024-05-03",
        "2024-05-02",
    ]


def test_footprints_infers_country_for_legacy_city_rows(tmp_path: Path) -> None:
    app, _, annotations = _build_app(tmp_path)
    client = app.test_client()
    assert client.put(
        "/api/days/2024-05-02/annotation",
        json={"places": [{"city": "成都", "name": "玉林路"}]},
    ).status_code == 200

    import sqlite3

    with sqlite3.connect(annotations) as connection:
        connection.execute(
            "UPDATE places SET country_code = '', country_name = '' WHERE city_name = '成都'"
        )

    day = client.get("/api/footprints").get_json()["places"][0]["days"][0]
    assert day["country_code"] == "CN"
    assert day["country_name"] == "China"


def test_record_update_edits_metadata_without_changing_photo_facts(
    tmp_path: Path,
) -> None:
    app, _, annotations = _build_app(tmp_path)
    client = app.test_client()
    assert client.put(
        "/api/days/2024-05-02/annotation",
        json={
            "places": [{"city": "深圳", "name": "人才公园"}],
            "featuredPhotos": [{"relativePath": "202405_a/one.jpg"}],
            "isPublic": True,
        },
    ).status_code == 200

    response = client.patch(
        "/api/records/2024-05-02",
        json={
            "displayDate": "2024-05-04",
            "places": [
                {
                    "city": "广州",
                    "name": "北京路，珠江边",
                    "countryCode": "CN",
                }
            ],
        },
    )

    assert response.status_code == 200
    saved = response.get_json()
    assert saved["date"] == "2024-05-02"
    assert saved["displayDate"] == "2024-05-04"
    assert saved["featuredPhotos"][0]["relativePath"] == "202405_a/one.jpg"
    assert saved["isPublic"] is True

    journey = client.get("/api/footprints").get_json()["places"][0]
    assert journey["date_label"] == "2024-05-04"
    assert journey["country_code"] == "CN"
    assert journey["city"] == "广州"
    assert journey["photo_count"] == 2
    assert journey["days"] == [
        {
            "capture_date": "2024-05-02",
            "display_date": "2024-05-04",
            "country_code": "CN",
            "country_name": "China",
            "city": "广州",
            "places": ["北京路，珠江边"],
            "photo_count": 2,
        }
    ]

    preview_trip = client.get("/api/trails-preview").get_json()["trips"][0]
    assert preview_trip["captureDate"] == "2024-05-02"
    assert preview_trip["date"] == "2024-05-04"
    manifest = export_public(
        tmp_path / "photo-index.sqlite3",
        annotations,
        tmp_path / "edited-date-export",
        dry_run=True,
    )
    assert manifest["trips"][0]["date"] == "2024-05-04"


def test_record_delete_removes_annotation_but_keeps_photo_facts(tmp_path: Path) -> None:
    app, _, _ = _build_app(tmp_path)
    client = app.test_client()
    assert client.put(
        "/api/days/2024-05-02/annotation",
        json={
            "places": [{"city": "深圳", "name": "人才公园"}],
            "featuredPhotos": [{"relativePath": "202405_a/one.jpg"}],
        },
    ).status_code == 200

    deleted = client.delete("/api/records/2024-05-02")

    assert deleted.status_code == 200
    day = client.get("/api/days/2024-05-02").get_json()
    assert day["photo_count"] == 2
    assert day["annotation"]["annotated"] is False
    assert day["annotation"]["featuredPhotos"] == []
    assert client.get("/api/footprints").get_json()["places"] == []
    assert client.delete("/api/records/2024-05-02").status_code == 404


def test_annotation_rejects_date_without_indexed_photos(tmp_path: Path) -> None:
    app, _, _ = _build_app(tmp_path)

    response = app.test_client().put(
        "/api/days/2024-05-07/annotation",
        json={"places": ["北京"], "note": "", "reviewed": True},
    )

    assert response.status_code == 404
    assert response.get_json()["error"] == "该日期没有可统计照片"


def test_thumbnail_is_cached_without_modifying_source(tmp_path: Path) -> None:
    app, source, _ = _build_app(tmp_path)
    photo = source / "202405_a" / "one.jpg"
    before = (photo.stat().st_size, photo.stat().st_mtime_ns)
    relative = quote("202405_a/one.jpg", safe="/")

    response = app.test_client().get(f"/api/photos/{relative}/thumbnail")

    assert response.status_code == 200
    assert response.content_type == "image/jpeg"
    assert response.data.startswith(b"\xff\xd8")
    assert (photo.stat().st_size, photo.stat().st_mtime_ns) == before
    assert list((tmp_path / "thumbnails").glob("*.jpg"))


def test_dashboard_and_invalid_inputs(tmp_path: Path) -> None:
    app, _, _ = _build_app(tmp_path, local_ui_dist=tmp_path / "unbuilt-ui")
    client = app.test_client()

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "Moments · 方舟旅迹" in dashboard.get_data(as_text=True)
    assert client.get("/api/overview?month=not-a-month").status_code == 400
    assert client.get("/api/days/not-a-date").status_code == 400


def test_day_data_and_featured_photos_are_saved_together(tmp_path: Path) -> None:
    app, source, annotations_path = _build_app(tmp_path)
    client = app.test_client()

    annotation = client.put(
        "/api/days/2024-05-02/annotation",
        json={
            "places": [
                {
                    "name": "西湖",
                    "city": "杭州",
                }
            ],
            "featuredPhotos": [
                {"relativePath": "202405_a/one.jpg", "caption": ""}
            ],
            "isPublic": True,
        },
    )
    assert annotation.status_code == 200
    assert annotation.get_json()["places"][0]["city"] == "杭州"
    assert annotation.get_json()["places"][0]["countryCode"] == "CN"
    assert annotation.get_json()["places"][0]["countryName"] == "China"
    assert "people" not in annotation.get_json()
    assert annotation.get_json()["featuredPhotos"][0]["relativePath"] == "202405_a/one.jpg"
    assert annotation.get_json()["isPublic"] is True

    day = client.get("/api/days/2024-05-02").get_json()
    by_path = {photo["relative_path"]: photo for photo in day["photos"]}
    assert by_path["202405_a/one.jpg"]["featured"] is True
    assert by_path["202405_a/two.jpg"]["featured"] is False

    restarted = create_app(
        index_path=tmp_path / "photo-index.sqlite3",
        annotation_path=annotations_path,
        thumbnail_root=tmp_path / "thumbnails-restarted",
        source_finder=lambda: source,
    )
    restarted.config.update(TESTING=True)
    restarted_day = restarted.test_client().get("/api/days/2024-05-02").get_json()
    assert restarted_day["annotation"]["places"][0]["city"] == "杭州"
    assert "people" not in restarted_day["annotation"]
    assert restarted_day["annotation"]["featuredPhotos"] == [
        {
            "caption": "",
            "relativePath": "202405_a/one.jpg",
            "sortOrder": 0,
        }
    ]

    invalid = client.put(
        "/api/days/2024-05-02/annotation",
        json={
            "places": [{"city": "杭州"}],
            "featuredPhotos": [
                {"relativePath": "202405_a/other.jpg", "caption": ""}
            ],
        },
    )
    assert invalid.status_code == 400


def test_unknown_city_requires_country_once_and_uses_it_for_export(
    tmp_path: Path,
) -> None:
    app, _, annotations_path = _build_app(tmp_path)
    client = app.test_client()
    unknown_city = "无法离线识别的测试城市"

    required = client.put(
        "/api/days/2024-05-02/annotation",
        json={"places": [{"city": unknown_city, "name": "测试地点"}]},
    )
    assert required.status_code == 422
    assert required.get_json()["code"] == "COUNTRY_REQUIRED"
    assert required.get_json()["city"] == unknown_city
    assert client.get("/api/days/2024-05-02").get_json()["annotation"]["annotated"] is False

    saved = client.put(
        "/api/days/2024-05-02/annotation",
        json={
            "places": [
                {
                    "city": unknown_city,
                    "name": "测试地点",
                    "countryCode": "CN",
                    "countryName": "中国",
                }
            ],
            "featuredPhotos": [{"relativePath": "202405_a/one.jpg"}],
            "isPublic": True,
        },
    )
    assert saved.status_code == 200
    assert saved.get_json()["places"][0]["countryCode"] == "CN"
    assert saved.get_json()["places"][0]["countryName"] == "China"

    reused = client.put(
        "/api/days/2024-05-03/annotation",
        json={"places": [{"city": unknown_city, "name": "另一个地点"}]},
    )
    assert reused.status_code == 200
    assert reused.get_json()["places"][0]["countryCode"] == "CN"

    preview = client.get("/api/trails-preview").get_json()
    assert preview["trips"][0]["places"][0]["countryCode"] == "CN"
    assert preview["trips"][0]["places"][0]["mapPoint"] is None
    assert preview["warnings"] == []

    manifest = export_public(
        tmp_path / "photo-index.sqlite3",
        annotations_path,
        tmp_path / "manual-country-export",
        dry_run=True,
    )
    assert manifest["trips"][0]["places"][0]["countryCode"] == "CN"

def test_trails_preview_uses_latest_public_annotations_without_export(
    tmp_path: Path,
) -> None:
    app, source, _ = _build_app(tmp_path)
    client = app.test_client()
    before = {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in source.rglob("*.jpg")
    }

    assert client.put(
        "/api/days/2024-05-02/annotation",
        json={
            "places": [{"city": "深圳", "name": "人才公园"}],
            "featuredPhotos": [{"relativePath": "202405_a/one.jpg"}],
            "isPublic": True,
        },
    ).status_code == 200
    assert client.put(
        "/api/days/2024-05-03/annotation",
        json={
            "places": [{"city": "广州", "name": ""}],
            "featuredPhotos": [{"relativePath": "202405_a/other.jpg"}],
            "isPublic": False,
        },
    ).status_code == 200

    response = client.get("/api/trails-preview")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["summary"] == {
        "tripDays": 1,
        "cities": 1,
        "countries": 1,
        "featuredPhotos": 1,
    }
    assert payload["warnings"] == []
    assert payload["trips"][0]["title"] == "深圳 · 人才公园"
    assert "people" not in payload["trips"][0]
    assert payload["trips"][0]["places"][0]["mapPoint"] == pytest.approx(
        [114.0683, 22.54554]
    )
    photo = payload["trips"][0]["photos"][0]
    assert client.get(photo["thumbnail"]).status_code == 200
    assert client.get(photo["src"]).status_code == 200
    after = {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in source.rglob("*.jpg")
    }
    assert after == before


def test_annotation_schema_migration_keeps_existing_rows(tmp_path: Path) -> None:
    path = tmp_path / "old-annotations.sqlite3"
    import sqlite3

    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE day_annotations (
                capture_date TEXT PRIMARY KEY,
                note TEXT NOT NULL DEFAULT '',
                reviewed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE places (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );
            CREATE TABLE people (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );
            CREATE TABLE day_places (
                capture_date TEXT NOT NULL REFERENCES day_annotations(capture_date) ON DELETE CASCADE,
                place_id INTEGER NOT NULL REFERENCES places(id),
                sort_order INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(capture_date, place_id)
            );
            CREATE TABLE day_people (
                capture_date TEXT NOT NULL REFERENCES day_annotations(capture_date) ON DELETE CASCADE,
                person_id INTEGER NOT NULL REFERENCES people(id),
                PRIMARY KEY(capture_date, person_id)
            );
            INSERT INTO day_annotations VALUES(
                '2024-01-02', '旧备注', NULL, '2024-01-03', '2024-01-03'
            );
            """
        )

    store = AnnotationStore(path)

    migrated = store.get("2024-01-02")
    assert migrated["note"] == "旧备注"
    assert migrated["displayDate"] == "2024-01-02"
    assert migrated["tripTitle"] == ""
    assert migrated["isPublic"] is False
    assert migrated["featuredPhotos"] == []


def test_day_can_return_all_photos_and_preview_urls(tmp_path: Path) -> None:
    app, _, _ = _build_app(tmp_path)
    import sqlite3

    with sqlite3.connect(tmp_path / "photo-index.sqlite3") as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(photos)")]
        row = list(connection.execute("SELECT * FROM photos WHERE relative_path = '202405_a/one.jpg'").fetchone())
        path_index = columns.index("relative_path")
        values = []
        for number in range(205):
            copy = list(row)
            copy[path_index] = f"202405_a/synthetic-{number}.jpg"
            values.append(copy)
        connection.executemany(f"INSERT INTO photos VALUES ({','.join('?' for _ in columns)})", values)
    client = app.test_client()
    payload = client.get("/api/days/2024-05-02?limit=all").get_json()
    assert payload["photos_returned"] == payload["photos_total"] > 200
    assert all(photo["preview_url"].endswith("/preview") for photo in payload["photos"])
    assert client.get(payload["photos"][0]["preview_url"]).status_code == 200
    assert client.get("/api/days/2024-05-02?limit=1").get_json()["photos_returned"] == 1


def test_background_preview_prepares_cached_snapshot_and_invalidates_after_save(tmp_path: Path) -> None:
    from test_background_tasks import wait_finished

    app, source, _ = _build_app(tmp_path)
    client = app.test_client()
    payload = {"places": [{"city": "深圳"}], "featuredPhotos": [{"relativePath": "202405_a/one.jpg"}], "isPublic": True}
    assert client.put("/api/days/2024-05-02/annotation", json=payload).status_code == 200
    assert client.get("/api/trails-preview?cached=1").status_code == 409
    before = (source / "202405_a/one.jpg").stat()
    assert client.post("/api/trails-preview/refresh").status_code == 202
    status = wait_finished(app.extensions["preview_service"])
    assert status["state"] == "complete" and status["ready"]
    assert status["completed"] == status["total"] == 1
    result = client.get("/api/trails-preview?cached=1").get_json()
    assert result["summary"]["featuredPhotos"] == 1
    cached = list((tmp_path / "thumbnails").glob("*.jpg"))
    assert len(cached) == 2
    cache_times = {item.name: item.stat().st_mtime_ns for item in cached}
    assert client.post("/api/trails-preview/refresh").status_code == 202
    assert wait_finished(app.extensions["preview_service"])["state"] == "complete"
    assert {item.name: item.stat().st_mtime_ns for item in cached} == cache_times
    after = (source / "202405_a/one.jpg").stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
    payload["places"] = [{"city": "广州"}]
    assert client.put("/api/days/2024-05-02/annotation", json=payload).status_code == 200
    assert not client.get("/api/trails-preview/status").get_json()["ready"]
    assert client.get("/api/trails-preview?cached=1").status_code == 409
    assert client.get("/api/trails-preview").get_json()["trips"][0]["places"][0]["city"] == "广州"


def test_index_preview_and_export_tasks_do_not_overlap(tmp_path: Path) -> None:
    import threading
    from test_background_tasks import wait_finished

    app, _, _ = _build_app(tmp_path)
    task = app.extensions["refresh_service"]
    entered, release = threading.Event(), threading.Event()

    def worker(progress):
        progress("读取拍摄日期", 1, 2)
        entered.set()
        assert release.wait(5)
        return {"message": "已完成"}

    task.worker = worker
    client = app.test_client()
    assert client.post("/api/index/refresh").status_code == 202
    try:
        assert entered.wait(5)
        assert client.post("/api/index/refresh").status_code == 409
        assert client.post("/api/trails-preview/refresh").status_code == 409
        assert client.post("/api/public-export/refresh").status_code == 409
        assert client.get("/api/index/status").get_json()["completed"] == 1
    finally:
        release.set()
    assert wait_finished(task)["state"] == "complete"


def test_preview_reuses_date_cache_across_app_restarts_and_only_updates_changed_day(tmp_path, monkeypatch):
    from test_background_tasks import wait_finished
    import pic_timeline.web as web

    app, source, annotations = _build_app(tmp_path)
    client = app.test_client()
    payload = {"places": [{"city": "深圳"}], "featuredPhotos": [{"relativePath": "202405_a/one.jpg"}], "isPublic": True}
    assert client.put("/api/days/2024-05-02/annotation", json=payload).status_code == 200
    client.post("/api/trails-preview/refresh")
    assert wait_finished(app.extensions["preview_service"])["state"] == "complete"
    restarted = create_app(index_path=tmp_path / "photo-index.sqlite3", annotation_path=annotations, thumbnail_root=tmp_path / "thumbnails", source_finder=lambda: source)
    client = restarted.test_client()
    original = web.infer_city
    calls = []

    def locate(city):
        calls.append(city)
        return original(city)

    monkeypatch.setattr(web, "infer_city", locate)
    client.post("/api/trails-preview/refresh")
    status = wait_finished(restarted.extensions["preview_service"])
    assert status["state"] == "complete" and not calls
    assert status["counters"] == {"dates_reused": 1, "dates_updated": 0}
    assert status["cache"]["reused"] == 1 and status["cache"]["pending"] == 0
    payload["places"] = [{"city": "广州"}]
    client.put("/api/days/2024-05-02/annotation", json=payload)
    calls.clear()
    client.post("/api/trails-preview/refresh")
    status = wait_finished(restarted.extensions["preview_service"])
    assert status["counters"]["dates_updated"] == 1
    assert calls == ["广州"]
    assert status["cache"]["pending"] == 0


def test_gui_export_creates_only_public_attachments_and_protects_private_files(tmp_path):
    from test_background_tasks import wait_finished
    import hashlib
    import zipfile
    from io import BytesIO

    app, source, _ = _build_app(tmp_path)
    client = app.test_client()
    payload = {"places": [{"city": "深圳"}], "featuredPhotos": [{"relativePath": "202405_a/one.jpg"}], "isPublic": True}
    assert client.put("/api/days/2024-05-02/annotation", json=payload).status_code == 200
    before = (source / "202405_a/one.jpg").stat()
    assert client.get("/api/public-export/files/public-data.zip").status_code == 409
    assert client.post("/api/public-export/refresh").status_code == 202
    status = wait_finished(app.extensions["public_export_service"])
    assert status["state"] == "complete" and status["ready"]
    assert status["artifacts"] == ["public-data.zip", "public-data.zip.sha256"]
    data = client.get("/api/public-export/files/public-data.zip").data
    checksum = client.get("/api/public-export/files/public-data.zip.sha256").data.decode("ascii")
    assert checksum.split()[0] == hashlib.sha256(data).hexdigest()
    with zipfile.ZipFile(BytesIO(data)) as archive:
        assert len(archive.namelist()) == 3
        assert "data/trips.json" in archive.namelist()
        assert all(name == "data/trips.json" or name.endswith(".webp") for name in archive.namelist())
        assert "relativePath" not in archive.read("data/trips.json").decode("utf-8")
    assert client.get("/api/public-export/files/annotations.sqlite3").status_code == 404
    after = (source / "202405_a/one.jpg").stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
    client.post("/api/public-export/refresh")
    status = wait_finished(app.extensions["public_export_service"])
    assert status["counters"] == {"reused": 1, "generated": 0}
    payload["isPublic"] = False
    client.put("/api/days/2024-05-02/annotation", json=payload)
    assert client.get("/api/public-export/files/public-data.zip").status_code == 409


def test_save_during_gui_export_marks_completed_result_stale(tmp_path):
    import threading
    from test_background_tasks import wait_finished

    app, _, _ = _build_app(tmp_path)
    task = app.extensions["public_export_service"]
    entered, release = threading.Event(), threading.Event()

    def worker(progress):
        progress("读取导出快照", 2, 2)
        entered.set()
        assert release.wait(5)
        return {"message": "已完成", "artifacts": ["public-data.zip", "public-data.zip.sha256"]}

    task.worker = worker
    client = app.test_client()
    assert client.post("/api/public-export/refresh").status_code == 202
    try:
        assert entered.wait(5)
        assert client.post("/api/public-export/refresh").status_code == 409
        assert client.post("/api/index/refresh").status_code == 409
        assert client.post("/api/trails-preview/refresh").status_code == 409
        assert client.put("/api/days/2024-05-02/annotation", json={"places": [{"city": "深圳"}]}).status_code == 200
    finally:
        release.set()
    status = wait_finished(task)
    assert status["state"] == "complete" and status["stale"] and not status["ready"]
    assert client.get("/api/public-export/files/public-data.zip").status_code == 409


@pytest.mark.parametrize("field", ["people", "person", "companion", "publicName", "public_name"])
@pytest.mark.parametrize("endpoint", ["annotation", "records"])
def test_retired_identity_fields_are_rejected_without_changing_data(
    tmp_path: Path, field: str, endpoint: str
) -> None:
    app, _, _ = _build_app(tmp_path)
    client = app.test_client()
    assert client.put(
        "/api/days/2024-05-02/annotation",
        json={"places": [{"city": "深圳", "name": "人才公园"}]},
    ).status_code == 200
    before = client.get("/api/days/2024-05-02").get_json()["annotation"]
    payload = {field: ["隐私测试标记"]}
    if endpoint == "annotation":
        response = client.put("/api/days/2024-05-02/annotation", json=payload)
    else:
        response = client.patch("/api/records/2024-05-02", json=payload)
    assert response.status_code == 400
    assert "不再支持" in response.get_json()["error"]
    assert client.get("/api/days/2024-05-02").get_json()["annotation"] == before


def test_legacy_identity_tables_are_removed_without_losing_other_data(tmp_path: Path) -> None:
    import sqlite3

    app, _, annotations = _build_app(tmp_path)
    client = app.test_client()
    assert client.put(
        "/api/days/2024-05-02/annotation",
        json={
            "places": [{"city": "深圳", "name": "人才公园"}],
            "featuredPhotos": [{"relativePath": "202405_a/one.jpg"}],
        },
    ).status_code == 200
    assert client.put("/api/settings", json={"defaultCity": "深圳"}).status_code == 200
    before = client.get("/api/days/2024-05-02").get_json()["annotation"]
    with sqlite3.connect(annotations) as connection:
        connection.executescript(
            """
            CREATE TABLE people (
                id INTEGER PRIMARY KEY, name TEXT, normalized_name TEXT,
                public_name TEXT, created_at TEXT
            );
            CREATE TABLE day_people (
                capture_date TEXT REFERENCES day_annotations(capture_date),
                person_id INTEGER REFERENCES people(id)
            );
            INSERT INTO people VALUES(1, '隐私测试标记', 'test', '隐私公开标记', '2024-01-01');
            INSERT INTO day_people VALUES('2024-05-02', 1);
            INSERT INTO app_settings VALUES('migration_vienna_companion_v1', 'complete', '2024-01-01');
            """
        )

    manifest = export_public(
        tmp_path / "photo-index.sqlite3", annotations,
        tmp_path / "legacy-export", dry_run=True,
    )
    store = AnnotationStore(annotations)
    assert store.get("2024-05-02") == before
    assert AnnotationStore(annotations).get("2024-05-02") == before
    assert store.settings()["defaultCity"] == "深圳"
    assert "people" not in store.options()
    with sqlite3.connect(annotations) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"people", "day_people"}.isdisjoint(tables)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    for endpoint in [
        "/api/overview?month=2024-05", "/api/days/2024-05-02", "/api/options",
        "/api/footprints", "/api/trails-preview",
    ]:
        payload = client.get(endpoint).get_json()
        text = json.dumps(payload, ensure_ascii=False)
        assert '"people"' not in text
        assert '"companion"' not in text
        assert "隐私测试标记" not in text
        assert "隐私公开标记" not in text
    exported = json.dumps(manifest, ensure_ascii=False)
    assert '"people"' not in exported
    assert "隐私公开标记" not in exported
    assert manifest["trips"][0]["places"][0]["city"] == "深圳"
    assert len(manifest["trips"][0]["photos"]) == 1


def test_public_export_is_a_strict_whitelist_and_strips_metadata(tmp_path: Path) -> None:
    app, source, annotations = _build_app(tmp_path)
    client = app.test_client()
    public_payload = {
        "places": [
            {
                "name": "西湖",
                "city": "杭州",
            }
        ],
        "tripTitle": "旧标题不应导出",
        "itinerary": "旧行程不应导出",
        "publicDescription": "旧公开说明不应导出",
        "note": "私密门牌号 123",
        "isPublic": True,
        "featuredPhotos": [
            {"relativePath": "202405_a/one.jpg", "caption": "旧照片说明"}
        ],
    }
    assert (
        client.put("/api/days/2024-05-02/annotation", json=public_payload).status_code
        == 200
    )
    assert (
        client.put(
            "/api/days/2024-05-03/annotation",
            json={
                "places": [
                    {
                        "name": "不应出现",
                        "city": "北京",
                    }
                ],
                "isPublic": True,
                "featuredPhotos": [],
            },
        ).status_code
        == 200
    )

    output = tmp_path / "public"
    progress_events: list[tuple[str, int, int]] = []
    manifest = export_public(
        tmp_path / "photo-index.sqlite3",
        annotations,
        output,
        progress=lambda stage, current, total: progress_events.append(
            (stage, current, total)
        ),
    )

    assert manifest["summary"] == {
        "tripDays": 1,
        "countries": 1,
        "featuredPhotos": 1,
    }
    assert "people" not in manifest["trips"][0]
    assert manifest["trips"][0]["title"] == "杭州 · 西湖"
    assert manifest["trips"][0]["places"][0]["city"] == "杭州"
    assert manifest["trips"][0]["places"][0]["countryCode"] == "CN"
    assert "itinerary" not in manifest["trips"][0]
    assert "description" not in manifest["trips"][0]
    assert "caption" not in manifest["trips"][0]["photos"][0]
    text = (output / "data" / "trips.json").read_text(encoding="utf-8")
    assert "私密门牌号" not in text
    assert "不应出现" not in text
    assert "旧标题不应导出" not in text
    assert "旧行程不应导出" not in text
    assert "旧公开说明不应导出" not in text
    assert "旧照片说明" not in text
    assert "202405_a" not in text
    assert str(source) not in text
    assert len(list((output / "media").glob("*.webp"))) == 2
    assert ("扫描图片缓存", 0, 1) in progress_events
    assert ("扫描图片缓存", 1, 1) in progress_events
    assert ("生成新增图片", 0, 1) in progress_events
    assert ("生成新增图片", 1, 1) in progress_events
    assert any(stage == "审计临时导出" for stage, _, _ in progress_events)
    assert any(stage == "复核最终导出" for stage, _, _ in progress_events)
    for image_path in (output / "media").glob("*.webp"):
        with Image.open(image_path) as image:
            assert not image.getexif()
            assert not image.info.get("exif")
    assert audit_public_tree(output, source_root=source)["webpFiles"] == 2


def test_public_export_console_progress_is_visible(
    capsys: pytest.CaptureFixture[str],
) -> None:
    progress = ConsoleProgress()

    progress("生成新增图片", 0, 100)
    progress("生成新增图片", 1, 100)
    progress("生成新增图片", 100, 100)

    output = capsys.readouterr().out
    assert "生成新增图片：0/100（0%）" in output
    assert "生成新增图片：1/100（1%）" in output
    assert "生成新增图片：100/100（100%）" in output
    assert "预计剩余" in output


def test_public_export_reuses_unchanged_webp_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, _, annotations = _build_app(tmp_path)
    client = app.test_client()
    assert client.put(
        "/api/days/2024-05-02/annotation",
        json={
            "places": [{"city": "深圳", "name": ""}],
            "featuredPhotos": [{"relativePath": "202405_a/one.jpg"}],
            "isPublic": True,
        },
    ).status_code == 200

    index = tmp_path / "photo-index.sqlite3"
    output = tmp_path / "incremental-public"
    first_stats = ExportStats()
    export_public(index, annotations, output, stats=first_stats)
    assert first_stats.generated_photos == 1
    assert first_stats.reused_photos == 0

    def reject_reencode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("未变化的照片不应重新编码")

    monkeypatch.setattr(
        "pic_timeline.export_public._write_webp_pair", reject_reencode
    )
    second_stats = ExportStats()
    status_messages: list[str] = []
    manifest = export_public(
        index,
        annotations,
        output,
        stats=second_stats,
        status=status_messages.append,
    )

    assert manifest["summary"]["featuredPhotos"] == 1
    assert second_stats.reused_photos == 1
    assert second_stats.generated_photos == 0
    assert status_messages == ["缓存扫描完成：可复用 1 张，待生成 0 张"]
    assert len(list((output / "media").glob("*.webp"))) == 2


def test_public_checkbox_controls_export_and_shenzhen_can_be_default(
    tmp_path: Path,
) -> None:
    app, _, annotations = _build_app(tmp_path)
    client = app.test_client()
    common_place = {
        "name": "",
        "city": "深圳",
    }
    assert client.put(
        "/api/days/2024-05-02/annotation",
        json={
            "places": [common_place],
            "featuredPhotos": [
                {"relativePath": "202405_a/one.jpg", "caption": ""}
            ],
            "isPublic": False,
        },
    ).status_code == 200
    assert client.put(
        "/api/days/2024-05-03/annotation",
        json={
            "places": [common_place],
            "featuredPhotos": [
                {"relativePath": "202405_a/other.jpg", "caption": ""}
            ],
            "isPublic": True,
        },
    ).status_code == 200

    manifest = export_public(
        tmp_path / "photo-index.sqlite3", annotations, tmp_path / "public-default"
    )

    assert manifest["summary"]["tripDays"] == 1
    assert manifest["trips"][0]["date"] == "2024-05-03"
    assert manifest["trips"][0]["title"] == "深圳"
    assert manifest["trips"][0]["places"][0]["countryCode"] == "CN"


def test_public_export_allows_optional_location_fields(tmp_path: Path) -> None:
    app, _, annotations = _build_app(tmp_path)
    client = app.test_client()
    response = client.put(
        "/api/days/2024-05-02/annotation",
        json={
            "places": [{"city": "", "name": "玉林路"}],
            "featuredPhotos": [{"relativePath": "202405_a/one.jpg"}],
            "isPublic": True,
        },
    )
    assert response.status_code == 200

    manifest = export_public(
        tmp_path / "photo-index.sqlite3", annotations, tmp_path / "public-optional"
    )

    assert manifest["summary"]["countries"] == 0
    assert manifest["trips"][0]["title"] == "玉林路"
    assert manifest["trips"][0]["places"][0]["countryCode"] == ""
    assert "people" not in manifest["trips"][0]


def test_port_check_detects_an_existing_server(capsys: pytest.CaptureFixture[str]) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = int(listener.getsockname()[1])

        assert _port_is_in_use("127.0.0.1", port) is True
        with pytest.raises(SystemExit) as stopped:
            main(["--port", str(port)])
        assert stopped.value.code == 2
        assert f"端口 {port} 已被占用" in capsys.readouterr().err

    assert _port_is_in_use("127.0.0.1", port) is False


@pytest.mark.parametrize(
    "forbidden_field",
    ["latitude", "longitude", "itinerary", "description", "caption",
     "people", "person", "companion", "publicName", "public_name"],
)
def test_public_audit_rejects_removed_fields(
    tmp_path: Path, forbidden_field: str
) -> None:
    output = tmp_path / "public"
    data = output / "data"
    data.mkdir(parents=True)
    (data / "trips.json").write_text(
        json.dumps({"trips": [{forbidden_field: "不应发布"}]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="公开 JSON 包含禁止字段"):
        audit_public_tree(output)
