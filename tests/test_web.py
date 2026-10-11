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


def _build_app(tmp_path: Path):
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
            json={"places": [{"city": city, "name": ""}], "people": []},
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
            "people": [],
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
            "people": ["朋友"],
            "note": "春天散步",
            "reviewed": True,
        },
    )
    assert response.status_code == 200
    saved = response.get_json()
    assert [item["name"] for item in saved["places"]] == ["杭州西湖"]
    assert [item["name"] for item in saved["people"]] == ["朋友"]
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
                "people": ["朋友"],
                "featuredPhotos": [{"relativePath": photo}],
                "isPublic": True,
            },
        ).status_code == 200

    journeys = client.get("/api/footprints").get_json()["places"]

    assert len(journeys) == 1
    assert journeys[0]["date_label"] == "2024-05-02 至 2024-05-03"
    assert journeys[0]["city"] == "深圳"
    assert journeys[0]["places"] == ["人才公园", "莲花山"]
    assert journeys[0]["people"] == ["朋友"]
    assert journeys[0]["photo_count"] == 3


def test_footprints_sort_separate_journeys_by_latest_date(tmp_path: Path) -> None:
    app, _, _ = _build_app(tmp_path)
    client = app.test_client()
    for capture_date, city in (("2024-05-02", "深圳"), ("2024-05-03", "广州")):
        assert client.put(
            f"/api/days/{capture_date}/annotation",
            json={"places": [{"city": city, "name": ""}], "people": []},
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
        json={"places": [{"city": "成都", "name": "玉林路"}], "people": []},
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
            "people": ["朋友"],
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
            "people": ["爱人"],
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
            "people": ["爱人"],
            "companion": "爱人",
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
            "people": ["朋友"],
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


def test_companion_is_limited_to_one_supported_value(tmp_path: Path) -> None:
    app, _, _ = _build_app(tmp_path)
    client = app.test_client()

    multiple = client.put(
        "/api/days/2024-05-02/annotation",
        json={"places": [{"city": "深圳"}], "people": ["朋友", "家人"]},
    )
    unsupported = client.put(
        "/api/days/2024-05-02/annotation",
        json={"places": [{"city": "深圳"}], "people": ["同事甲"]},
    )

    assert multiple.status_code == 400
    assert "只能选择一项" in multiple.get_json()["error"]
    assert unsupported.status_code == 400
    assert "只能选择爱人" in unsupported.get_json()["error"]


@pytest.mark.parametrize("people", [[], [""], ["空"], ["不填写"], ["无"]])
def test_empty_companion_values_are_saved_as_no_companion(
    tmp_path: Path, people: list[str]
) -> None:
    app, _, _ = _build_app(tmp_path)
    response = app.test_client().put(
        "/api/days/2024-05-02/annotation",
        json={"places": [{"city": "深圳"}], "people": people},
    )

    assert response.status_code == 200
    assert [person["name"] for person in response.get_json()["people"]] == ["无"]


def test_annotation_rejects_date_without_indexed_photos(tmp_path: Path) -> None:
    app, _, _ = _build_app(tmp_path)

    response = app.test_client().put(
        "/api/days/2024-05-07/annotation",
        json={"places": ["北京"], "people": [], "note": "", "reviewed": True},
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
    app, _, _ = _build_app(tmp_path)
    client = app.test_client()

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "Moments Studio" in dashboard.get_data(as_text=True)
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
            "people": ["朋友"],
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
    assert annotation.get_json()["people"][0]["publicName"] == "朋友"
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
    assert restarted_day["annotation"]["people"][0]["name"] == "朋友"
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
            "people": [],
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
        json={"places": [{"city": unknown_city, "name": "测试地点"}], "people": []},
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
            "people": [],
            "featuredPhotos": [{"relativePath": "202405_a/one.jpg"}],
            "isPublic": True,
        },
    )
    assert saved.status_code == 200
    assert saved.get_json()["places"][0]["countryCode"] == "CN"
    assert saved.get_json()["places"][0]["countryName"] == "China"

    reused = client.put(
        "/api/days/2024-05-03/annotation",
        json={"places": [{"city": unknown_city, "name": "另一个地点"}], "people": []},
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
            "people": [{"name": "朋友", "publicName": "朋友"}],
            "featuredPhotos": [{"relativePath": "202405_a/one.jpg"}],
            "isPublic": True,
        },
    ).status_code == 200
    assert client.put(
        "/api/days/2024-05-03/annotation",
        json={
            "places": [{"city": "广州", "name": ""}],
            "people": [],
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
    assert payload["trips"][0]["people"] == ["朋友"]
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


def test_companion_schema_migration_normalizes_legacy_names(tmp_path: Path) -> None:
    path = tmp_path / "legacy-companions.sqlite3"
    AnnotationStore(path)
    import sqlite3

    legacy_names = ["爸爸", "妈妈", "宝宝", "室友"]
    with sqlite3.connect(path) as connection:
        for index, name in enumerate(legacy_names, start=1):
            capture_date = f"2024-01-{index:02d}"
            connection.execute(
                """
                INSERT INTO day_annotations(
                    capture_date, display_date, created_at, updated_at
                ) VALUES(?, ?, '2024-01-01', '2024-01-01')
                """,
                (capture_date, capture_date),
            )
            person_id = connection.execute(
                """
                INSERT INTO people(name, normalized_name, public_name, created_at)
                VALUES(?, ?, ?, '2024-01-01')
                RETURNING id
                """,
                (name, name.casefold(), name),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO day_people(capture_date, person_id) VALUES(?, ?)",
                (capture_date, person_id),
            )

    migrated = AnnotationStore(path)
    assert [migrated.get(f"2024-01-{day:02d}")["people"][0]["name"] for day in range(1, 5)] == [
        "家人",
        "家人",
        "爱人",
        "同学",
    ]
    assert {person["name"] for person in migrated.options()["people"]}.isdisjoint(
        legacy_names
    )


def test_vienna_companion_migration_runs_once(tmp_path: Path) -> None:
    path = tmp_path / "vienna-companions.sqlite3"
    store = AnnotationStore(path)
    place = {
        "name": "美泉宫",
        "city": "维也纳",
        "countryCode": "AT",
        "countryName": "Austria",
        "latitude": None,
        "longitude": None,
    }
    store.save(
        "2024-01-01",
        display_date="2024-01-01",
        places=[place],
        people=[{"name": "朋友", "publicName": "朋友"}],
        trip_title="",
        itinerary="",
        note="",
        public_description="",
        is_public=True,
        reviewed=False,
    )

    import sqlite3

    with sqlite3.connect(path) as connection:
        connection.execute(
            "DELETE FROM app_settings WHERE key = 'migration_vienna_companion_v1'"
        )
    migrated = AnnotationStore(path)
    assert migrated.get("2024-01-01")["people"][0]["name"] == "同事"

    migrated.save(
        "2024-01-01",
        display_date="2024-01-01",
        places=[place],
        people=[{"name": "爱人", "publicName": "爱人"}],
        trip_title="",
        itinerary="",
        note="",
        public_description="",
        is_public=True,
        reviewed=False,
    )
    assert AnnotationStore(path).get("2024-01-01")["people"][0]["name"] == "爱人"


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
        "people": ["朋友"],
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
                "people": [],
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
    assert manifest["trips"][0]["people"] == ["朋友"]
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
            "people": [],
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
            "people": [],
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
            "people": [],
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
            "people": [],
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
    assert manifest["trips"][0]["people"] == []


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
    ["latitude", "longitude", "itinerary", "description", "caption"],
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
