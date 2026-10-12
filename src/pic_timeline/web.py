from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import os
import re
import socket
import sqlite3
import threading
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from flask import (
    Flask,
    abort,
    jsonify,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)
from PIL import Image, ImageOps

from .analysis import find_source_root, scan_archive
from .city_country import country_from_code, infer_city
from .public_package import PRIVATE_IDENTITY_FIELDS


class CountryRequiredError(ValueError):
    def __init__(self, city: str, reason: str):
        super().__init__(f"无法根据城市“{city}”推导国家，请选择国家")
        self.city = city
        self.reason = reason


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("日期必须使用 YYYY-MM-DD 格式") from exc


def _clean_names(values: object, field_name: str) -> list[str]:
    if not isinstance(values, list):
        raise ValueError(f"{field_name}必须是数组")
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"{field_name}只能包含文本")
        cleaned = value.strip()
        if not cleaned:
            continue
        if len(cleaned) > 80:
            raise ValueError(f"{field_name}中的名称不能超过 80 个字符")
        key = cleaned.casefold()
        if key not in seen:
            seen.add(key)
            result.append(cleaned)
    if len(result) > 20:
        raise ValueError(f"{field_name}最多包含 20 项")
    return result


def _clean_places(values: object) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        raise ValueError("地点必须是数组")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        item = {"name": value} if isinstance(value, str) else value
        if not isinstance(item, dict):
            raise ValueError("地点格式无效")
        name = str(item.get("name", "")).strip()
        city = str(item.get("city", "")).strip()
        country_code = str(item.get("countryCode", "")).strip().upper()
        country_name = str(item.get("countryName", "")).strip()
        if not name and not city:
            continue
        if len(name) > 500 or len(city) > 80 or len(country_name) > 80:
            raise ValueError("城市和国家名称不能超过 80 个字符，地点不能超过 500 个字符")
        if country_code and not re.fullmatch(r"[A-Z]{2}", country_code):
            raise ValueError("国家代码必须使用两个大写英文字母")
        key = "|".join((city, name)).casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "name": name,
                "city": city,
                "countryCode": country_code if city else "",
                "countryName": country_name if city else "",
                "latitude": None,
                "longitude": None,
            }
        )
    if len(result) > 20:
        raise ValueError("地点最多包含 20 项")
    return result


def _reject_private_fields(payload: dict[str, Any]) -> None:
    if PRIVATE_IDENTITY_FIELDS & payload.keys():
        raise ValueError("不再支持同行人字段，请刷新页面")


def _clean_text(payload: dict[str, Any], key: str, label: str, limit: int) -> str:
    value = payload.get(key, "")
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{label}必须是最多 {limit} 个字符的文本")
    return value.strip()


def _clean_featured(values: object) -> list[dict[str, str]]:
    if not isinstance(values, list):
        raise ValueError("精选照片必须是数组")
    if len(values) > 30:
        raise ValueError("每个日期最多精选 30 张照片")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("精选照片格式无效")
        relative_path = value.get("relativePath")
        caption = value.get("caption", "")
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ValueError("精选照片缺少相对路径")
        if not isinstance(caption, str) or len(caption) > 300:
            raise ValueError("照片说明必须是最多 300 个字符的文本")
        relative_path = relative_path.strip().replace("\\", "/")
        if relative_path.casefold() in seen:
            continue
        seen.add(relative_path.casefold())
        result.append({"relativePath": relative_path, "caption": caption.strip()})
    return result


class PhotoIndex:
    def __init__(self, path: Path):
        self.path = path.resolve()

    def _connect(self) -> sqlite3.Connection:
        if not self.path.is_file():
            raise FileNotFoundError(f"照片索引不存在：{self.path}")
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def metadata(self) -> dict[str, str]:
        with self._connect() as connection:
            return {
                row["key"]: row["value"]
                for row in connection.execute("SELECT key, value FROM metadata")
            }

    def available_months(self) -> list[str]:
        with self._connect() as connection:
            return [
                row[0]
                for row in connection.execute(
                    """
                    SELECT DISTINCT substr(capture_date, 1, 7)
                    FROM photos
                    WHERE capture_date <> ''
                    ORDER BY 1
                    """
                )
            ]

    def overview_counts(self, month: str) -> dict[str, int]:
        with self._connect() as connection:
            return {
                row["capture_date"]: row["photo_count"]
                for row in connection.execute(
                    """
                    SELECT capture_date, COUNT(*) AS photo_count
                    FROM photos
                    WHERE capture_date LIKE ? AND date_source LIKE 'exif:%'
                    GROUP BY capture_date
                    ORDER BY capture_date
                    """,
                    (f"{month}%",),
                )
            }

    def totals(self) -> dict[str, int]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS photos,
                    SUM(CASE WHEN capture_date <> '' THEN 1 ELSE 0 END) AS included,
                    SUM(CASE WHEN capture_date = '' THEN 1 ELSE 0 END) AS missing
                FROM photos
                """
            ).fetchone()
        return {
            "photos": int(row["photos"] or 0),
            "included": int(row["included"] or 0),
            "missing": int(row["missing"] or 0),
        }

    def count_for_date(self, capture_date: str) -> int:
        with self._connect() as connection:
            return int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM photos
                    WHERE capture_date = ? AND date_source LIKE 'exif:%'
                    """,
                    (capture_date,),
                ).fetchone()[0]
            )

    def photos_for_date(
        self,
        capture_date: str,
        limit: int = 60,
        offset: int = 0,
        featured_paths: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        with self._connect() as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM photos WHERE capture_date = ?",
                    (capture_date,),
                ).fetchone()[0]
            )
            featured_paths = featured_paths or []
            if featured_paths:
                placeholders = ",".join("?" for _ in featured_paths)
                order_clause = (
                    f"CASE WHEN relative_path IN ({placeholders}) THEN 0 ELSE 1 END, "
                    "capture_time, relative_path"
                )
                order_values: tuple[Any, ...] = tuple(featured_paths)
            else:
                order_clause = "capture_time, relative_path"
                order_values = ()
            rows = connection.execute(
                f"""
                SELECT relative_path, extension, size, mtime_ns, capture_time
                FROM photos
                WHERE capture_date = ?
                ORDER BY {order_clause}
                LIMIT ? OFFSET ?
                """,
                (capture_date, *order_values, limit, offset),
            ).fetchall()
        return [dict(row) for row in rows], total

    def validate_paths_for_date(
        self, capture_date: str, relative_paths: list[str]
    ) -> bool:
        if not relative_paths:
            return True
        placeholders = ",".join("?" for _ in relative_paths)
        with self._connect() as connection:
            count = connection.execute(
                f"""
                SELECT COUNT(*) FROM photos
                WHERE capture_date = ? AND relative_path IN ({placeholders})
                """,
                (capture_date, *relative_paths),
            ).fetchone()[0]
        return int(count) == len(set(relative_paths))

    def photo(self, relative_path: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT relative_path, extension, size, mtime_ns, capture_date
                FROM photos WHERE relative_path = ?
                """,
                (relative_path,),
            ).fetchone()
        return dict(row) if row else None

    def counts_by_date(self) -> dict[str, int]:
        with self._connect() as connection:
            return {
                row["capture_date"]: int(row["photo_count"])
                for row in connection.execute(
                    """
                    SELECT capture_date, COUNT(*) AS photo_count
                    FROM photos
                    WHERE capture_date <> '' AND date_source LIKE 'exif:%'
                    GROUP BY capture_date
                    """
                )
            }


class AnnotationStore:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS day_annotations (
                    capture_date TEXT PRIMARY KEY,
                    display_date TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    trip_title TEXT NOT NULL DEFAULT '',
                    itinerary TEXT NOT NULL DEFAULT '',
                    public_description TEXT NOT NULL DEFAULT '',
                    is_public INTEGER NOT NULL DEFAULT 1,
                    reviewed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS places (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL UNIQUE,
                    country_code TEXT NOT NULL DEFAULT '',
                    country_name TEXT NOT NULL DEFAULT '',
                    city_name TEXT NOT NULL DEFAULT '',
                    latitude REAL,
                    longitude REAL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS day_places (
                    capture_date TEXT NOT NULL REFERENCES day_annotations(capture_date) ON DELETE CASCADE,
                    place_id INTEGER NOT NULL REFERENCES places(id),
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(capture_date, place_id)
                );
                CREATE INDEX IF NOT EXISTS idx_day_places_place ON day_places(place_id);
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                """
            )

            self._ensure_column(
                connection,
                "day_annotations",
                "display_date",
                "TEXT NOT NULL DEFAULT ''",
            )
            connection.execute(
                """
                UPDATE day_annotations
                SET display_date = capture_date
                WHERE TRIM(display_date) = ''
                """
            )
            self._ensure_column(
                connection,
                "day_annotations",
                "trip_title",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                connection,
                "day_annotations",
                "itinerary",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                connection,
                "day_annotations",
                "public_description",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                connection,
                "day_annotations",
                "is_public",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                connection, "places", "country_code", "TEXT NOT NULL DEFAULT ''"
            )
            self._ensure_column(
                connection, "places", "country_name", "TEXT NOT NULL DEFAULT ''"
            )
            self._ensure_column(
                connection, "places", "city_name", "TEXT NOT NULL DEFAULT ''"
            )
            self._ensure_column(connection, "places", "latitude", "REAL")
            self._ensure_column(connection, "places", "longitude", "REAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS day_featured_photos (
                    capture_date TEXT NOT NULL REFERENCES day_annotations(capture_date) ON DELETE CASCADE,
                    relative_path TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    caption TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(capture_date, relative_path)
                );
                CREATE INDEX IF NOT EXISTS idx_featured_date_order
                    ON day_featured_photos(capture_date, sort_order);
                """
            )
            # Retire only the legacy companion tables; other annotations stay intact.
            connection.execute("PRAGMA secure_delete = ON")
            connection.execute("DROP TABLE IF EXISTS day_people")
            connection.execute("DROP TABLE IF EXISTS people")
            connection.execute(
                "DELETE FROM app_settings WHERE key = ?",
                ("migration_vienna_companion_v1",),
            )

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        columns = {
            row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _place_id(
        connection: sqlite3.Connection, place: dict[str, Any], timestamp: str
    ) -> int:
        normalized = "|".join((place["city"], place["name"])).casefold()
        connection.execute(
            """
            INSERT INTO places(
                name, normalized_name, country_code, country_name, city_name,
                latitude, longitude, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(normalized_name) DO UPDATE SET
                name = excluded.name,
                country_code = CASE WHEN excluded.country_code <> ''
                    THEN excluded.country_code ELSE places.country_code END,
                country_name = CASE WHEN excluded.country_name <> ''
                    THEN excluded.country_name ELSE places.country_name END,
                city_name = CASE WHEN excluded.city_name <> ''
                    THEN excluded.city_name ELSE places.city_name END,
                latitude = COALESCE(excluded.latitude, places.latitude),
                longitude = COALESCE(excluded.longitude, places.longitude)
            """,
            (
                place["name"],
                normalized,
                place["countryCode"],
                place["countryName"],
                place["city"],
                place["latitude"],
                place["longitude"],
                timestamp,
            ),
        )
        return int(
            connection.execute(
                "SELECT id FROM places WHERE normalized_name = ?", (normalized,)
            ).fetchone()[0]
        )

    def save(
        self,
        capture_date: str,
        *,
        display_date: str,
        places: list[dict[str, Any]],
        trip_title: str,
        itinerary: str,
        note: str,
        public_description: str,
        is_public: bool,
        reviewed: bool,
        featured_photos: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        timestamp = _now()
        with self._connect() as connection:
            stored_featured_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM day_featured_photos WHERE capture_date = ?",
                    (capture_date,),
                ).fetchone()[0]
            )
            featured_count = (
                stored_featured_count
                if featured_photos is None
                else len(featured_photos)
            )
            if not any(
                (
                    places,
                    trip_title,
                    itinerary,
                    note,
                    public_description,
                    is_public,
                    reviewed,
                    featured_count,
                    display_date != capture_date,
                )
            ):
                connection.execute(
                    "DELETE FROM day_annotations WHERE capture_date = ?",
                    (capture_date,),
                )
                return self.empty(capture_date)

            reviewed_at = timestamp if reviewed else None
            connection.execute(
                """
                INSERT INTO day_annotations(
                    capture_date, display_date, trip_title, itinerary, note,
                    public_description, is_public, reviewed_at,
                    created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(capture_date) DO UPDATE SET
                    display_date = excluded.display_date,
                    trip_title = excluded.trip_title,
                    itinerary = excluded.itinerary,
                    note = excluded.note,
                    public_description = excluded.public_description,
                    is_public = excluded.is_public,
                    reviewed_at = excluded.reviewed_at,
                    updated_at = excluded.updated_at
                """,
                (
                    capture_date,
                    display_date,
                    trip_title,
                    itinerary,
                    note,
                    public_description,
                    int(is_public),
                    reviewed_at,
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                "DELETE FROM day_places WHERE capture_date = ?", (capture_date,)
            )
            for index, place in enumerate(places):
                place_id = self._place_id(connection, place, timestamp)
                connection.execute(
                    "INSERT INTO day_places(capture_date, place_id, sort_order) VALUES(?, ?, ?)",
                    (capture_date, place_id, index),
                )
            if featured_photos is not None:
                connection.execute(
                    "DELETE FROM day_featured_photos WHERE capture_date = ?",
                    (capture_date,),
                )
                for sort_order, photo in enumerate(featured_photos):
                    connection.execute(
                        """
                        INSERT INTO day_featured_photos(
                            capture_date, relative_path, sort_order, caption
                        ) VALUES(?, ?, ?, ?)
                        """,
                        (
                            capture_date,
                            photo["relativePath"],
                            sort_order,
                            photo["caption"],
                        ),
                    )
        return self.get(capture_date)

    def save_featured(
        self, capture_date: str, photos: list[dict[str, str]]
    ) -> dict[str, Any]:
        timestamp = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO day_annotations(
                    capture_date, display_date, is_public, created_at, updated_at
                )
                VALUES(?, ?, 1, ?, ?)
                ON CONFLICT(capture_date) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (capture_date, capture_date, timestamp, timestamp),
            )
            connection.execute(
                "DELETE FROM day_featured_photos WHERE capture_date = ?",
                (capture_date,),
            )
            for sort_order, photo in enumerate(photos):
                connection.execute(
                    """
                    INSERT INTO day_featured_photos(
                        capture_date, relative_path, sort_order, caption
                    ) VALUES(?, ?, ?, ?)
                    """,
                    (
                        capture_date,
                        photo["relativePath"],
                        sort_order,
                        photo["caption"],
                    ),
                )
        return self.get(capture_date)

    @staticmethod
    def empty(capture_date: str) -> dict[str, Any]:
        return {
            "date": capture_date,
            "displayDate": capture_date,
            "places": [],
            "tripTitle": "",
            "itinerary": "",
            "note": "",
            "publicDescription": "",
            "isPublic": True,
            "reviewed": False,
            "reviewed_at": None,
            "featuredPhotos": [],
            "annotated": False,
        }

    def get(self, capture_date: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM day_annotations WHERE capture_date = ?",
                (capture_date,),
            ).fetchone()
            if row is None:
                return self.empty(capture_date)
            places = [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "city": item["city_name"],
                    "countryCode": item["country_code"],
                    "countryName": item["country_name"],
                }
                for item in connection.execute(
                    """
                    SELECT places.id, places.name, places.city_name,
                           places.country_code, places.country_name
                    FROM day_places
                    JOIN places ON places.id = day_places.place_id
                    WHERE day_places.capture_date = ?
                    ORDER BY day_places.sort_order, places.name
                    """,
                    (capture_date,),
                )
            ]
            featured = [
                {
                    "relativePath": item["relative_path"],
                    "caption": item["caption"],
                    "sortOrder": item["sort_order"],
                }
                for item in connection.execute(
                    """
                    SELECT relative_path, caption, sort_order
                    FROM day_featured_photos
                    WHERE capture_date = ?
                    ORDER BY sort_order, relative_path
                    """,
                    (capture_date,),
                )
            ]
        return {
            "date": capture_date,
            "displayDate": str(row["display_date"] or capture_date),
            "places": places,
            "tripTitle": row["trip_title"],
            "itinerary": row["itinerary"],
            "note": row["note"],
            "publicDescription": row["public_description"],
            "isPublic": bool(row["is_public"]),
            "reviewed": row["reviewed_at"] is not None,
            "reviewed_at": row["reviewed_at"],
            "featuredPhotos": featured,
            "annotated": True,
        }

    def list_between(self, start: str, end: str) -> dict[str, dict[str, Any]]:
        with self._connect() as connection:
            dates = [
                row[0]
                for row in connection.execute(
                    """
                    SELECT capture_date FROM day_annotations
                    WHERE capture_date BETWEEN ? AND ?
                    ORDER BY capture_date
                    """,
                    (start, end),
                )
            ]
        return {capture_date: self.get(capture_date) for capture_date in dates}

    def all(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            dates = [
                row[0]
                for row in connection.execute(
                    "SELECT capture_date FROM day_annotations ORDER BY capture_date"
                )
            ]
        return [self.get(capture_date) for capture_date in dates]

    def delete(self, capture_date: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM day_annotations WHERE capture_date = ?", (capture_date,)
            )
        return cursor.rowcount > 0

    def cities(self) -> list[str]:
        with self._connect() as connection:
            return [
                str(row["city"])
                for row in connection.execute(
                    """
                    SELECT DISTINCT TRIM(places.city_name) AS city
                    FROM day_places
                    JOIN places ON places.id = day_places.place_id
                    WHERE TRIM(places.city_name) <> ''
                    ORDER BY city COLLATE NOCASE
                    """
                )
            ]

    def country_for_city(self, city: str) -> dict[str, str] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT country_code, country_name
                FROM places
                WHERE TRIM(city_name) = ? AND country_code <> ''
                ORDER BY id DESC
                LIMIT 1
                """,
                (city.strip(),),
            ).fetchone()
        if row is None:
            return None
        try:
            country = country_from_code(str(row["country_code"]))
        except ValueError:
            return None
        return {"countryCode": country.code, "countryName": country.name}

    def settings(self) -> dict[str, Any]:
        available_cities = self.cities()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM app_settings WHERE key = 'default_city'"
            ).fetchone()
        stored = str(row["value"]).strip() if row is not None else ""
        canonical = {city.casefold(): city for city in available_cities}
        return {
            "defaultCity": canonical.get(stored.casefold(), ""),
            "availableCities": available_cities,
        }

    def save_settings(self, default_city: str) -> dict[str, Any]:
        cleaned = default_city.strip()
        if len(cleaned) > 80:
            raise ValueError("缺省城市不能超过 80 个字符")
        available_cities = self.cities()
        canonical = {city.casefold(): city for city in available_cities}
        if cleaned and cleaned.casefold() not in canonical:
            raise ValueError("缺省城市必须从已有记录的城市中选择")
        value = canonical.get(cleaned.casefold(), "")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO app_settings(key, value, updated_at)
                VALUES('default_city', ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (value, _now()),
            )
        return self.settings()

    def options(self) -> dict[str, list[dict[str, Any]]]:
        with self._connect() as connection:
            places = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT id, name, city_name AS city
                    FROM places ORDER BY normalized_name
                    """
                )
            ]
        return {"places": places}


class RefreshService:
    def __init__(self, index_path: Path, source_finder: Callable[[], Path]):
        self.index_path = index_path
        self.source_finder = source_finder
        self._lock = threading.Lock()
        self._status: dict[str, Any] = {
            "state": "idle",
            "started_at": None,
            "finished_at": None,
            "message": "",
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def start(self) -> bool:
        with self._lock:
            if self._status["state"] == "running":
                return False
            self._status = {
                "state": "running",
                "started_at": _now(),
                "finished_at": None,
                "message": "正在更新照片索引",
            }
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()
        return True

    def _run(self) -> None:
        try:
            source_root = self.source_finder()
            records, _, counters = scan_archive(source_root, self.index_path)
            result = {
                "state": "complete",
                "started_at": self.status()["started_at"],
                "finished_at": _now(),
                "message": f"索引已更新，共 {len(records)} 张照片",
                "counters": dict(counters),
            }
        except Exception as exc:
            result = {
                "state": "error",
                "started_at": self.status()["started_at"],
                "finished_at": _now(),
                "message": str(exc),
            }
        with self._lock:
            self._status = result


def create_app(
    *,
    index_path: Path | str = Path("data/photo_index.sqlite3"),
    annotation_path: Path | str = Path("data/annotations.sqlite3"),
    thumbnail_root: Path | str = Path("data/thumbnails"),
    local_ui_dist: Path | str | None = None,
    source_finder: Callable[[], Path] = find_source_root,
) -> Flask:
    app = Flask(__name__)
    photo_index = PhotoIndex(Path(index_path))
    annotations = AnnotationStore(Path(annotation_path))
    thumbnail_root = Path(thumbnail_root).resolve()
    thumbnail_root.mkdir(parents=True, exist_ok=True)
    local_ui_dist = (
        Path(local_ui_dist).resolve()
        if local_ui_dist is not None
        else Path(__file__).resolve().parents[2] / "apps" / "local-ui" / "dist"
    )
    refresh_service = RefreshService(Path(index_path).resolve(), source_finder)

    def enrich_places(values: object) -> list[dict[str, Any]]:
        places = _clean_places(values)
        for place in places:
            city = place["city"]
            if not city:
                continue
            if place["countryCode"]:
                country = country_from_code(place["countryCode"])
                place["countryCode"] = country.code
                place["countryName"] = country.name
                continue
            try:
                city_match = infer_city(city)
            except ValueError as exc:
                stored_country = annotations.country_for_city(city)
                if stored_country is None:
                    raise CountryRequiredError(city, str(exc)) from exc
                place.update(stored_country)
            else:
                place.update(
                    {
                        "countryCode": city_match.code,
                        "countryName": city_match.name,
                        "latitude": city_match.latitude,
                        "longitude": city_match.longitude,
                    }
                )
        return places

    def serve_cached_photo(
        relative_path: str,
        *,
        max_size: tuple[int, int],
        quality: int,
        variant: str,
    ):
        record = photo_index.photo(relative_path)
        if record is None:
            abort(404)
        metadata = photo_index.metadata()
        source_root = Path(metadata.get("source_root", "")).resolve()
        source_path = (source_root / relative_path).resolve()
        if not source_path.is_relative_to(source_root) or not source_path.is_file():
            abort(404)
        cache_key = hashlib.sha256(
            (
                f"{variant}|{relative_path}|{record['size']}|"
                f"{record['mtime_ns']}"
            ).encode("utf-8")
        ).hexdigest()
        cached = thumbnail_root / f"{cache_key}.jpg"
        if not cached.exists():
            previous_limit = Image.MAX_IMAGE_PIXELS
            Image.MAX_IMAGE_PIXELS = None
            try:
                with Image.open(source_path) as source:
                    image = ImageOps.exif_transpose(source)
                    image.thumbnail(max_size)
                    if image.mode not in ("RGB", "L"):
                        background = Image.new("RGB", image.size, "white")
                        if "A" in image.getbands():
                            background.paste(image, mask=image.getchannel("A"))
                        else:
                            background.paste(image)
                        image = background
                    elif image.mode == "L":
                        image = image.convert("RGB")
                    image.save(cached, "JPEG", quality=quality, optimize=True)
            finally:
                Image.MAX_IMAGE_PIXELS = previous_limit
        return send_file(cached, mimetype="image/jpeg", conditional=True)

    @app.errorhandler(ValueError)
    def handle_value_error(exc: ValueError):
        if request.path.startswith("/api/"):
            return jsonify({"error": str(exc)}), 400
        return str(exc), 400

    @app.errorhandler(CountryRequiredError)
    def handle_country_required(exc: CountryRequiredError):
        return (
            jsonify(
                {
                    "error": str(exc),
                    "code": "COUNTRY_REQUIRED",
                    "city": exc.city,
                    "reason": exc.reason,
                }
            ),
            422,
        )

    @app.errorhandler(FileNotFoundError)
    def handle_file_error(exc: FileNotFoundError):
        if request.path.startswith("/api/"):
            return jsonify({"error": str(exc)}), 503
        return str(exc), 503

    @app.get("/")
    def dashboard():
        if (local_ui_dist / "index.html").is_file():
            return send_from_directory(local_ui_dist, "index.html")
        return render_template("index.html")

    @app.get("/assets/<path:filename>")
    def local_ui_asset(filename: str):
        if not local_ui_dist.is_dir():
            abort(404)
        return send_from_directory(local_ui_dist / "assets", filename)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "apiVersion": 2, "pid": os.getpid()})

    @app.get("/api/overview")
    def overview():
        months = photo_index.available_months()
        if not months:
            return jsonify({"error": "索引中没有可统计的拍摄日期"}), 409
        selected = request.args.get("month", months[-1])
        if not selected or len(selected) != 7 or selected[4] != "-":
            raise ValueError("月份必须使用 YYYY-MM 格式")
        try:
            year, month_number = (int(part) for part in selected.split("-"))
            days_in_month = calendar.monthrange(year, month_number)[1]
        except (ValueError, TypeError) as exc:
            raise ValueError("月份必须使用 YYYY-MM 格式") from exc

        start = f"{selected}-01"
        end = f"{selected}-{days_in_month:02d}"
        counts = photo_index.overview_counts(selected)
        month_annotations = annotations.list_between(start, end)
        days = []
        for day_number in range(1, days_in_month + 1):
            capture_date = f"{selected}-{day_number:02d}"
            annotation = month_annotations.get(
                capture_date, AnnotationStore.empty(capture_date)
            )
            days.append(
                {
                    "date": capture_date,
                    "day": day_number,
                    "count": counts.get(capture_date, 0),
                    "annotation": annotation,
                }
            )
        nonzero = [item for item in days if item["count"]]
        max_day = max(nonzero, key=lambda item: item["count"], default=None)
        metadata = photo_index.metadata()
        totals = photo_index.totals()
        return jsonify(
            {
                "selected_month": selected,
                "available_months": months,
                "available_years": sorted({month[:4] for month in months}),
                "days": days,
                "summary": {
                    "month_photos": sum(counts.values()),
                    "active_days": len(nonzero),
                    "annotated_days": sum(
                        item["annotation"]["annotated"] for item in nonzero
                    ),
                    "featured_days": sum(
                        bool(item["annotation"]["featuredPhotos"])
                        for item in nonzero
                    ),
                    "reviewed_days": sum(
                        item["annotation"]["reviewed"] for item in nonzero
                    ),
                    "max_day": max_day,
                    **totals,
                },
                "source_root": metadata.get("source_root", ""),
                "refresh": refresh_service.status(),
            }
        )

    @app.get("/api/days/<capture_date>")
    def day_detail(capture_date: str):
        _parse_date(capture_date)
        photo_count = photo_index.count_for_date(capture_date)
        if photo_count == 0:
            abort(404)
        try:
            limit = min(max(int(request.args.get("limit", "60")), 1), 200)
            offset = max(int(request.args.get("offset", "0")), 0)
        except ValueError as exc:
            raise ValueError("照片分页参数必须是整数") from exc
        annotation = annotations.get(capture_date)
        featured = {
            item["relativePath"]: item for item in annotation["featuredPhotos"]
        }
        photos, total = photo_index.photos_for_date(
            capture_date,
            limit,
            offset,
            featured_paths=list(featured),
        )
        for photo in photos:
            photo["thumbnail_url"] = url_for(
                "photo_thumbnail", relative_path=photo["relative_path"]
            )
            selected = featured.get(photo["relative_path"])
            photo["featured"] = selected is not None
            photo["caption"] = selected["caption"] if selected else ""
        return jsonify(
            {
                "date": capture_date,
                "photo_count": photo_count,
                "annotation": annotation,
                "photos": photos,
                "photos_returned": len(photos),
                "photos_total": total,
                "offset": offset,
            }
        )

    @app.put("/api/days/<capture_date>/annotation")
    def save_annotation(capture_date: str):
        _parse_date(capture_date)
        if photo_index.count_for_date(capture_date) == 0:
            return jsonify({"error": "该日期没有可统计照片"}), 404
        payload = request.get_json(silent=False)
        if not isinstance(payload, dict):
            raise ValueError("请求内容必须是 JSON 对象")
        _reject_private_fields(payload)
        current = annotations.get(capture_date)
        display_date = str(payload.get("displayDate", current["displayDate"])).strip()
        _parse_date(display_date)
        places = enrich_places(payload.get("places", []))
        trip_title = _clean_text(payload, "tripTitle", "行程标题", 120)
        itinerary = _clean_text(payload, "itinerary", "行程", 4000)
        note = _clean_text(payload, "note", "私人备注", 4000)
        public_description = _clean_text(
            payload, "publicDescription", "公开说明", 4000
        )
        is_public = payload.get("isPublic", True)
        reviewed = payload.get("reviewed", False)
        featured_photos = None
        if "featuredPhotos" in payload:
            featured_photos = _clean_featured(payload["featuredPhotos"])
            relative_paths = [item["relativePath"] for item in featured_photos]
            if not photo_index.validate_paths_for_date(capture_date, relative_paths):
                raise ValueError("精选照片必须属于当前日期且存在于照片索引中")
        if not isinstance(is_public, bool):
            raise ValueError("公开状态必须是布尔值")
        if not isinstance(reviewed, bool):
            raise ValueError("已整理状态必须是布尔值")
        saved = annotations.save(
            capture_date,
            display_date=display_date,
            places=places,
            trip_title=trip_title,
            itinerary=itinerary,
            note=note,
            public_description=public_description,
            is_public=is_public,
            reviewed=reviewed,
            featured_photos=featured_photos,
        )
        return jsonify(saved)

    @app.patch("/api/records/<capture_date>")
    def update_record(capture_date: str):
        _parse_date(capture_date)
        current = annotations.get(capture_date)
        if not current["annotated"]:
            return jsonify({"error": "该日期还没有标注记录"}), 404
        payload = request.get_json(silent=False)
        if not isinstance(payload, dict):
            raise ValueError("请求内容必须是 JSON 对象")
        _reject_private_fields(payload)
        display_date = str(payload.get("displayDate", current["displayDate"])).strip()
        _parse_date(display_date)
        places = enrich_places(payload.get("places", current["places"]))
        saved = annotations.save(
            capture_date,
            display_date=display_date,
            places=places,
            trip_title=current["tripTitle"],
            itinerary=current["itinerary"],
            note=current["note"],
            public_description=current["publicDescription"],
            is_public=current["isPublic"],
            reviewed=current["reviewed"],
            featured_photos=None,
        )
        return jsonify(saved)

    @app.delete("/api/records/<capture_date>")
    def delete_record(capture_date: str):
        _parse_date(capture_date)
        if not annotations.delete(capture_date):
            return jsonify({"error": "该日期还没有标注记录"}), 404
        return jsonify({"deleted": capture_date})

    @app.put("/api/days/<capture_date>/featured")
    def save_featured(capture_date: str):
        _parse_date(capture_date)
        if photo_index.count_for_date(capture_date) == 0:
            return jsonify({"error": "该日期没有可统计照片"}), 404
        payload = request.get_json(silent=False)
        if not isinstance(payload, dict):
            raise ValueError("请求内容必须是 JSON 对象")
        photos = _clean_featured(payload.get("photos", []))
        relative_paths = [item["relativePath"] for item in photos]
        if not photo_index.validate_paths_for_date(capture_date, relative_paths):
            raise ValueError("精选照片必须属于当前日期且存在于照片索引中")
        return jsonify(annotations.save_featured(capture_date, photos))

    @app.get("/api/options")
    def options():
        return jsonify(annotations.options())

    @app.get("/api/settings")
    def get_settings():
        return jsonify(annotations.settings())

    @app.put("/api/settings")
    def save_settings():
        payload = request.get_json(silent=False)
        if not isinstance(payload, dict):
            raise ValueError("请求内容必须是 JSON 对象")
        default_city = payload.get("defaultCity", "")
        if not isinstance(default_city, str):
            raise ValueError("缺省城市必须是文本")
        return jsonify(annotations.save_settings(default_city))

    @app.get("/api/footprints")
    def footprints():
        counts = photo_index.counts_by_date()
        days = []
        for annotation in annotations.all():
            city = next(
                (
                    str(place["city"] or "").strip()
                    for place in annotation["places"]
                    if str(place["city"] or "").strip()
                ),
                "",
            )
            first_place = annotation["places"][0] if annotation["places"] else {}
            country_code = str(first_place.get("countryCode") or "").strip().upper()
            country_name = str(first_place.get("countryName") or "").strip()
            if country_code:
                try:
                    stored_country = country_from_code(country_code)
                except ValueError:
                    pass
                else:
                    country_code = stored_country.code
                    country_name = stored_country.name
            elif city:
                try:
                    inferred_country = infer_city(city)
                except ValueError:
                    pass
                else:
                    country_code = inferred_country.code
                    country_name = inferred_country.name
            days.append(
                {
                    "capture_date": annotation["date"],
                    "display_date": annotation["displayDate"],
                    "country_code": country_code,
                    "country_name": country_name,
                    "city": city,
                    "places": sorted(
                        {
                            str(place["name"] or "").strip()
                            for place in annotation["places"]
                            if str(place["name"] or "").strip()
                        }
                    ),
                    "photo_count": counts.get(annotation["date"], 0),
                }
            )

        journeys: list[dict[str, Any]] = []
        for day in sorted(
            days, key=lambda item: (item["display_date"], item["capture_date"])
        ):
            previous = journeys[-1] if journeys else None
            is_adjacent = bool(
                previous
                and day["city"]
                and previous["city"].casefold() == day["city"].casefold()
                and (
                    date.fromisoformat(day["display_date"])
                    - date.fromisoformat(previous["end_date"])
                ).days
                == 1
            )
            if is_adjacent:
                previous["end_date"] = day["display_date"]
                previous["places"].update(day["places"])
                previous["photo_count"] += day["photo_count"]
                previous["days"].append(day)
                continue
            journeys.append(
                {
                    "start_date": day["display_date"],
                    "end_date": day["display_date"],
                    "country_code": day["country_code"],
                    "country_name": day["country_name"],
                    "city": day["city"],
                    "places": set(day["places"]),
                    "photo_count": day["photo_count"],
                    "days": [day],
                }
            )

        result = []
        for journey in reversed(journeys):
            start_date = journey["start_date"]
            end_date = journey["end_date"]
            result.append(
                {
                    "id": f"{start_date}|{end_date}|{journey['city']}",
                    "start_date": start_date,
                    "end_date": end_date,
                    "date_label": (
                        start_date if start_date == end_date else f"{start_date} 至 {end_date}"
                    ),
                    "country_code": journey["country_code"],
                    "country_name": journey["country_name"],
                    "city": journey["city"],
                    "places": sorted(journey["places"]),
                    "photo_count": journey["photo_count"],
                    "days": list(reversed(journey["days"])),
                }
            )
        return jsonify({"places": result})

    @app.get("/api/trails-preview")
    def trails_preview():
        trips: list[dict[str, Any]] = []
        warnings: list[str] = []
        city_keys: set[str] = set()
        country_codes: set[str] = set()
        featured_count = 0

        for annotation in annotations.all():
            if not annotation["isPublic"] or not annotation["featuredPhotos"]:
                continue
            places = []
            for place in annotation["places"]:
                city = str(place["city"] or "").strip()
                stored_country_code = str(place.get("countryCode") or "").strip().upper()
                stored_country_name = str(place.get("countryName") or "").strip()
                public_place: dict[str, Any] = {
                    "name": str(place["name"] or "").strip(),
                    "city": city,
                    "countryCode": stored_country_code,
                    "countryName": stored_country_name,
                    "mapPoint": None,
                }
                if city:
                    try:
                        city_match = infer_city(city)
                    except ValueError as exc:
                        if not stored_country_code:
                            warnings.append(f"{annotation['date']}：{exc}")
                    else:
                        if not stored_country_code:
                            public_place.update(
                                {
                                    "countryCode": city_match.code,
                                    "countryName": city_match.name,
                                }
                            )
                        if public_place["countryCode"] == city_match.code:
                            public_place["mapPoint"] = [
                                round(city_match.longitude, 5),
                                round(city_match.latitude, 5),
                            ]
                    if public_place["countryCode"]:
                        country_codes.add(public_place["countryCode"])
                        city_keys.add(f"{public_place['countryCode']}|{city}")
                places.append(public_place)

            photos = []
            for selected in annotation["featuredPhotos"]:
                relative_path = selected["relativePath"]
                record = photo_index.photo(relative_path)
                if record is None or record["capture_date"] != annotation["date"]:
                    warnings.append(
                        f"{annotation['date']}：精选照片已不在当天索引中"
                    )
                    continue
                public_id = hashlib.sha256(
                    f"{annotation['date']}|{relative_path}".encode("utf-8")
                ).hexdigest()[:20]
                photos.append(
                    {
                        "id": public_id,
                        "src": url_for(
                            "photo_preview_image", relative_path=relative_path
                        ),
                        "thumbnail": url_for(
                            "photo_thumbnail", relative_path=relative_path
                        ),
                    }
                )
            if not photos:
                continue

            title_parts = []
            if places:
                title_parts = [places[0]["city"], places[0]["name"]]
            trips.append(
                {
                    "id": f"trip-{annotation['date']}",
                    "captureDate": annotation["date"],
                    "date": annotation["displayDate"],
                    "year": int(annotation["displayDate"][:4]),
                    "title": " · ".join(part for part in title_parts if part)
                    or "照片记录",
                    "places": places,
                    "photos": photos,
                }
            )
            featured_count += len(photos)

        trips.sort(key=lambda item: item["date"], reverse=True)
        return jsonify(
            {
                "summary": {
                    "tripDays": len(trips),
                    "cities": len(city_keys),
                    "countries": len(country_codes),
                    "featuredPhotos": featured_count,
                },
                "trips": trips,
                "warnings": sorted(set(warnings)),
            }
        )

    @app.get("/api/photos/<path:relative_path>/thumbnail")
    def photo_thumbnail(relative_path: str):
        return serve_cached_photo(
            relative_path,
            max_size=(480, 360),
            quality=84,
            variant="thumbnail-v1",
        )

    @app.get("/api/photos/<path:relative_path>/preview")
    def photo_preview_image(relative_path: str):
        return serve_cached_photo(
            relative_path,
            max_size=(1600, 1200),
            quality=88,
            variant="preview-v1",
        )

    @app.post("/api/index/refresh")
    def refresh_index():
        started = refresh_service.start()
        return jsonify(refresh_service.status()), 202 if started else 409

    @app.get("/api/index/status")
    def refresh_status():
        return jsonify(refresh_service.status())

    app.extensions["photo_index"] = photo_index
    app.extensions["annotation_store"] = annotations
    app.extensions["refresh_service"] = refresh_service
    return app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local photo timeline app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--source", type=Path, help="原始照片目录，只读")
    parser.add_argument("--index", type=Path, default=Path("data/photo_index.sqlite3"))
    parser.add_argument(
        "--annotations", type=Path, default=Path("data/annotations.sqlite3")
    )
    return parser


def _port_is_in_use(host: str, port: int) -> bool:
    target = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    try:
        with socket.create_connection((target, port), timeout=0.25):
            return True
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if _port_is_in_use(args.host, args.port):
        parser.error(
            f"端口 {args.port} 已被占用；请先关闭旧服务，"
            "或使用 --port 指定其他端口"
        )
    source_finder = (lambda: args.source.resolve()) if args.source else find_source_root
    app = create_app(
        index_path=args.index,
        annotation_path=args.annotations,
        source_finder=source_finder,
    )
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
