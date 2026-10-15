from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

from .city_country import country_from_code, infer_country
from .public_package import PRIVATE_IDENTITY_FIELDS, PRIVATE_PATH_FIELDS
from .photo_sources import resolve_photo_path
from .web import AnnotationStore

register_heif_opener()

FORBIDDEN_JSON_FIELDS = {
    *PRIVATE_IDENTITY_FIELDS,
    *PRIVATE_PATH_FIELDS,
    "caption",
    "description",
    "itinerary",
    "latitude",
    "longitude",
    "note",
    "privateName",
    "publicDescription",
    "relativePath",
    "relative_path",
    "sourceRoot",
    "source_root",
    "tripTitle",
    "absolutePath",
    "absolute_path",
}
TEXT_EXTENSIONS = {".json", ".html", ".js", ".css", ".map", ".txt", ".xml"}
WINDOWS_PATH_PATTERN = re.compile(r"(?i)(?:[a-z]:[\\/]|\\\\[^\\]+[\\/])")
LOCALHOST_PATTERN = re.compile(r"(?i)(?:localhost|127\.0\.0\.1|file://)")
ProgressCallback = Callable[[str, int, int], None]
StatusCallback = Callable[[str], None]
IMAGE_CACHE_VERSION = 1
IMAGE_CACHE_MARKER = ".media-cache-version"


@dataclass
class ExportStats:
    reused_photos: int = 0
    generated_photos: int = 0


@dataclass(frozen=True)
class CachedWebpPair:
    full_path: Path
    thumbnail_path: Path
    width: int
    height: int


@dataclass(frozen=True)
class PlannedPhoto:
    source_path: Path
    public_id: str
    cached: CachedWebpPair | None


class ConsoleProgress:
    def __init__(self) -> None:
        self._stage = ""
        self._started_at = time.monotonic()
        self._last_percent = -1

    @staticmethod
    def _duration(seconds: float) -> str:
        value = max(0, round(seconds))
        minutes, remainder = divmod(value, 60)
        if minutes:
            return f"{minutes} 分 {remainder} 秒"
        return f"{remainder} 秒"

    def __call__(self, stage: str, current: int, total: int) -> None:
        if stage != self._stage:
            self._stage = stage
            self._started_at = time.monotonic()
            self._last_percent = -1

        if total <= 0:
            if self._last_percent < 0:
                print(f"{stage}：没有需要处理的文件", flush=True)
                self._last_percent = 100
            return

        percent = min(100, current * 100 // total)
        interval = 1 if stage == "生成新增图片" else 10
        if current not in (0, total) and percent < self._last_percent + interval:
            return
        self._last_percent = percent

        elapsed = time.monotonic() - self._started_at
        timing = f"已用 {self._duration(elapsed)}"
        if 0 < current < total:
            remaining = elapsed / current * (total - current)
            timing += f"，预计剩余 {self._duration(remaining)}"
        print(
            f"{stage}：{current}/{total}（{percent}%），{timing}",
            flush=True,
        )


def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(f"数据库不存在：{path}")
    if readonly:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only = ON")
    else:
        connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _source_root(index_path: Path) -> Path:
    with _connect(index_path, readonly=True) as connection:
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'source_root'"
        ).fetchone()
    if row is None:
        raise ValueError("照片索引缺少 source_root 元数据")
    root = Path(row["value"]).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"原始照片目录不存在：{root}")
    return root


def _public_rows(annotation_path: Path) -> list[sqlite3.Row]:
    AnnotationStore(annotation_path)
    with _connect(annotation_path, readonly=True) as connection:
        return connection.execute(
            """
            SELECT capture_date,
                   COALESCE(NULLIF(display_date, ''), capture_date) AS display_date
            FROM day_annotations
            WHERE is_public = 1 AND EXISTS (
                SELECT 1 FROM day_featured_photos
                WHERE day_featured_photos.capture_date = day_annotations.capture_date
            )
            ORDER BY capture_date
            """
        ).fetchall()


def _places(connection: sqlite3.Connection, capture_date: str) -> list[dict[str, Any]]:
    return [
        {
            "name": row["name"],
            "city": row["city_name"],
            "countryCode": row["country_code"],
            "countryName": row["country_name"],
        }
        for row in connection.execute(
            """
            SELECT places.name, places.city_name,
                   places.country_code, places.country_name
            FROM day_places
            JOIN places ON places.id = day_places.place_id
            WHERE day_places.capture_date = ?
            ORDER BY day_places.sort_order, places.normalized_name
            """,
            (capture_date,),
        )
    ]


def _featured(connection: sqlite3.Connection, capture_date: str) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT relative_path
        FROM day_featured_photos
        WHERE capture_date = ?
        ORDER BY sort_order, relative_path
        """,
        (capture_date,),
    ).fetchall()


def _public_photo_count(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM day_featured_photos
        JOIN day_annotations USING (capture_date)
        WHERE day_annotations.is_public = 1
        """
    ).fetchone()
    return int(row["count"])


def _indexed_photo(
    connection: sqlite3.Connection, capture_date: str, relative_path: str
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT relative_path, size, mtime_ns
        FROM photos
        WHERE capture_date = ? AND relative_path = ? AND date_source LIKE 'exif:%'
        """,
        (capture_date, relative_path),
    ).fetchone()
    if row is None:
        raise ValueError(f"精选照片不属于公开日期或已不在索引中：{capture_date}")
    return row


def _rgb_copy(image: Image.Image) -> Image.Image:
    if image.mode == "RGB":
        return image.copy()
    if "A" in image.getbands():
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _write_webp_pair(
    source_path: Path, media_root: Path, public_id: str
) -> tuple[str, str, int, int]:
    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = None
    try:
        with Image.open(source_path) as source:
            oriented = ImageOps.exif_transpose(source)
            clean = _rgb_copy(oriented)
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit

    full = clean.copy()
    full.thumbnail((1920, 1440), Image.Resampling.LANCZOS)
    thumbnail = clean.copy()
    thumbnail.thumbnail((640, 480), Image.Resampling.LANCZOS)
    clean.close()

    full_name = f"{public_id}.webp"
    thumbnail_name = f"{public_id}-thumb.webp"
    full.save(media_root / full_name, "WEBP", quality=84, method=6)
    thumbnail.save(media_root / thumbnail_name, "WEBP", quality=78, method=6)
    width, height = full.size
    full.close()
    thumbnail.close()
    return f"media/{full_name}", f"media/{thumbnail_name}", width, height


def _validated_cached_webp(path: Path) -> tuple[int, int] | None:
    if not path.is_file():
        return None
    try:
        with Image.open(path) as image:
            if image.format != "WEBP":
                return None
            if image.getexif() or image.info.get("exif") or image.info.get("xmp"):
                return None
            size = image.size
            image.verify()
    except (OSError, SyntaxError, ValueError):
        return None
    return size


def _cached_webp_pair(
    cache_root: Path, public_id: str
) -> CachedWebpPair | None:
    full_name = f"{public_id}.webp"
    thumbnail_name = f"{public_id}-thumb.webp"
    cached_full = cache_root / full_name
    cached_thumbnail = cache_root / thumbnail_name
    full_size = _validated_cached_webp(cached_full)
    thumbnail_size = _validated_cached_webp(cached_thumbnail)
    if full_size is None or thumbnail_size is None:
        return None
    if full_size[0] > 1920 or full_size[1] > 1440:
        return None
    if thumbnail_size[0] > 640 or thumbnail_size[1] > 480:
        return None

    return CachedWebpPair(
        full_path=cached_full,
        thumbnail_path=cached_thumbnail,
        width=full_size[0],
        height=full_size[1],
    )


def _materialize_cached_webp_pair(
    cached: CachedWebpPair, media_root: Path, public_id: str
) -> None:
    for source, target in (
        (cached.full_path, media_root / f"{public_id}.webp"),
        (cached.thumbnail_path, media_root / f"{public_id}-thumb.webp"),
    ):
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)


def _public_photo_id(capture_date: str, indexed: sqlite3.Row) -> str:
    return hashlib.sha256(
        (
            f"{capture_date}|{indexed['relative_path']}|"
            f"{indexed['size']}|{indexed['mtime_ns']}"
        ).encode("utf-8")
    ).hexdigest()[:20]


def _compatible_cache_root(output_root: Path) -> Path | None:
    media_root = output_root / "media"
    if not media_root.is_dir():
        return None
    marker = output_root / IMAGE_CACHE_MARKER
    if not marker.exists():
        # Existing exports were produced by the same v1 image profile.
        return media_root
    try:
        version = int(marker.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    return media_root if version == IMAGE_CACHE_VERSION else None


def _check_json_fields(value: Any, location: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_JSON_FIELDS:
                raise ValueError(f"公开 JSON 包含禁止字段：{location}.{key}")
            if re.search(r"(?i)(?:secret|password|token|api[_-]?key)", key):
                raise ValueError(f"公开 JSON 包含疑似密钥字段：{location}.{key}")
            _check_json_fields(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _check_json_fields(child, f"{location}[{index}]")


def audit_public_tree(
    root: Path,
    *,
    source_root: Path | None = None,
    progress: ProgressCallback | None = None,
    progress_stage: str = "审计公开文件",
) -> dict[str, int]:
    if not root.is_dir():
        raise FileNotFoundError(f"待检查目录不存在：{root}")
    text_files = 0
    webp_files = 0
    source_text = str(source_root) if source_root else ""
    files = sorted(item for item in root.rglob("*") if item.is_file())
    if progress:
        progress(progress_stage, 0, len(files))
    for completed, path in enumerate(files, start=1):
        if path.suffix.lower() in TEXT_EXTENSIONS:
            text_files += 1
            content = path.read_text(encoding="utf-8")
            if WINDOWS_PATH_PATTERN.search(content) or LOCALHOST_PATTERN.search(content):
                raise ValueError(f"发布文件包含本地地址或绝对路径：{path.name}")
            if source_text and source_text.casefold() in content.casefold():
                raise ValueError(f"发布文件泄露原始照片目录：{path.name}")
            if path.suffix.lower() == ".json":
                _check_json_fields(json.loads(content))
        if path.suffix.lower() == ".webp":
            webp_files += 1
            with Image.open(path) as image:
                if image.getexif():
                    raise ValueError(f"公开图片仍包含 EXIF：{path.name}")
                if image.info.get("exif") or image.info.get("xmp"):
                    raise ValueError(f"公开图片仍包含 EXIF/XMP 数据：{path.name}")
        if progress:
            progress(progress_stage, completed, len(files))
    return {"textFiles": text_files, "webpFiles": webp_files}


def build_public_manifest(
    index_path: Path,
    annotation_path: Path,
    stage_root: Path,
    *,
    write_images: bool,
    progress: ProgressCallback | None = None,
    status: StatusCallback | None = None,
    cache_root: Path | None = None,
    stats: ExportStats | None = None,
) -> dict[str, Any]:
    _source_root(index_path)
    rows = _public_rows(annotation_path)
    (stage_root / "data").mkdir(parents=True, exist_ok=True)
    media_root = stage_root / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    trips: list[dict[str, Any]] = []
    countries: dict[str, str] = {}
    photo_count = 0

    with (
        _connect(annotation_path, readonly=True) as annotation_db,
        _connect(index_path, readonly=True) as index_db,
    ):
        source_metadata = dict(index_db.execute("SELECT key, value FROM metadata"))
        total_photo_count = _public_photo_count(annotation_db)
        planned_photos: dict[str, list[PlannedPhoto]] = {}
        if write_images and progress:
            progress("扫描图片缓存", 0, total_photo_count)
        scanned_photos = 0
        for row in rows:
            capture_date = row["capture_date"]
            day_photos: list[PlannedPhoto] = []
            for selected in _featured(annotation_db, capture_date):
                indexed = _indexed_photo(
                    index_db, capture_date, selected["relative_path"]
                )
                source_path = resolve_photo_path(source_metadata, indexed["relative_path"])
                public_id = _public_photo_id(capture_date, indexed)
                cached = (
                    _cached_webp_pair(cache_root, public_id)
                    if write_images and cache_root is not None
                    else None
                )
                day_photos.append(
                    PlannedPhoto(
                        source_path=source_path,
                        public_id=public_id,
                        cached=cached,
                    )
                )
                scanned_photos += 1
                if write_images and progress:
                    progress("扫描图片缓存", scanned_photos, total_photo_count)
            planned_photos[capture_date] = day_photos

        export_stats = stats if stats is not None else ExportStats()
        export_stats.reused_photos = sum(
            photo.cached is not None
            for day_photos in planned_photos.values()
            for photo in day_photos
        )
        export_stats.generated_photos = scanned_photos - export_stats.reused_photos
        if write_images and status:
            status(
                f"缓存扫描完成：可复用 {export_stats.reused_photos} 张，"
                f"待生成 {export_stats.generated_photos} 张"
            )

        if write_images and progress:
            progress("复用缓存图片", 0, export_stats.reused_photos)
        reused_completed = 0
        if write_images:
            for day_photos in planned_photos.values():
                for photo in day_photos:
                    if photo.cached is None:
                        continue
                    _materialize_cached_webp_pair(
                        photo.cached, media_root, photo.public_id
                    )
                    reused_completed += 1
                    if progress:
                        progress(
                            "复用缓存图片",
                            reused_completed,
                            export_stats.reused_photos,
                        )

        if write_images and progress:
            progress("生成新增图片", 0, export_stats.generated_photos)
        generated_completed = 0
        for row in rows:
            capture_date = row["capture_date"]
            display_date = row["display_date"]
            places = []
            for local_place in _places(annotation_db, capture_date):
                country_code = str(local_place["countryCode"] or "").strip().upper()
                country_name = str(local_place["countryName"] or "").strip()
                if country_code:
                    country = country_from_code(country_code)
                    country_code = country.code
                    country_name = country.name
                elif local_place["city"]:
                    try:
                        country = infer_country(local_place["city"])
                    except ValueError as exc:
                        raise ValueError(f"{capture_date}：{exc}") from exc
                    country_code = country.code
                    country_name = country.name
                places.append(
                    {
                        "name": local_place["name"],
                        "city": local_place["city"],
                        "countryCode": country_code,
                        "countryName": country_name,
                    }
                )
            for place in places:
                if place["countryCode"]:
                    countries[place["countryCode"]] = place["countryName"]
            photos: list[dict[str, Any]] = []
            for planned in planned_photos[capture_date]:
                digest = planned.public_id
                if write_images:
                    if planned.cached is not None:
                        src = f"media/{digest}.webp"
                        thumbnail = f"media/{digest}-thumb.webp"
                        width = planned.cached.width
                        height = planned.cached.height
                    else:
                        src, thumbnail, width, height = _write_webp_pair(
                            planned.source_path, media_root, digest
                        )
                        generated_completed += 1
                        if progress:
                            progress(
                                "生成新增图片",
                                generated_completed,
                                export_stats.generated_photos,
                            )
                else:
                    src, thumbnail, width, height = (
                        f"media/{digest}.webp",
                        f"media/{digest}-thumb.webp",
                        0,
                        0,
                    )
                photos.append(
                    {
                        "id": digest,
                        "src": src,
                        "thumbnail": thumbnail,
                        "width": width,
                        "height": height,
                    }
                )
                photo_count += 1
            trips.append(
                {
                    "id": f"trip-{capture_date}",
                    "date": display_date,
                    "year": int(display_date[:4]),
                    "title": (
                        " · ".join(
                            part
                            for part in (places[0]["city"], places[0]["name"])
                            if part
                        )
                        if places
                        else "照片记录"
                    ),
                    "places": places,
                    "photos": photos,
                }
            )

    manifest = {
        "version": 1,
        "generatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "summary": {
            "tripDays": len(trips),
            "countries": len(countries),
            "featuredPhotos": photo_count,
        },
        "countries": [
            {"code": code, "name": countries[code]} for code in sorted(countries)
        ],
        "trips": trips,
    }
    _check_json_fields(manifest)
    (stage_root / "data" / "trips.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def export_public(
    index_path: Path,
    annotation_path: Path,
    output_root: Path,
    *,
    dry_run: bool = False,
    progress: ProgressCallback | None = None,
    status: StatusCallback | None = None,
    stats: ExportStats | None = None,
) -> dict[str, Any]:
    index_path = index_path.resolve()
    annotation_path = annotation_path.resolve()
    output_root = output_root.resolve()
    export_stats = stats if stats is not None else ExportStats()
    export_stats.reused_photos = 0
    export_stats.generated_photos = 0
    cache_root = None if dry_run else _compatible_cache_root(output_root)
    output_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".public-export-", dir=output_root.parent
    ) as temporary:
        stage_root = Path(temporary)
        manifest = build_public_manifest(
            index_path,
            annotation_path,
            stage_root,
            write_images=not dry_run,
            progress=progress,
            status=status,
            cache_root=cache_root,
            stats=export_stats,
        )
        if dry_run:
            return manifest
        source_root = _source_root(index_path)
        audit_public_tree(
            stage_root,
            source_root=source_root,
            progress=progress,
            progress_stage="审计临时导出",
        )
        if progress:
            progress("替换本地导出", 0, 1)
        output_root.mkdir(parents=True, exist_ok=True)
        for name in ("data", "media"):
            target = output_root / name
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(stage_root / name), str(target))
        if progress:
            progress("替换本地导出", 1, 1)
    audit_public_tree(
        output_root,
        source_root=_source_root(index_path),
        progress=progress,
        progress_stage="复核最终导出",
    )
    (output_root / IMAGE_CACHE_MARKER).write_text(
        f"{IMAGE_CACHE_VERSION}\n", encoding="ascii"
    )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="导出公开旅行时间线与精选照片")
    parser.add_argument("--index", type=Path, default=Path("data/db/photo_index.sqlite3"))
    parser.add_argument(
        "--annotations", type=Path, default=Path("data/db/annotations.sqlite3")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/exports/public-data")
    )
    parser.add_argument("--dry-run", action="store_true", help="仅校验并列出导出数量")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    progress = None if args.dry_run else ConsoleProgress()
    status = None if args.dry_run else lambda message: print(message, flush=True)
    stats = ExportStats()
    manifest = export_public(
        args.index,
        args.annotations,
        args.output,
        dry_run=args.dry_run,
        progress=progress,
        status=status,
        stats=stats,
    )
    summary = manifest["summary"]
    action = "试运行完成" if args.dry_run else "公开导出完成"
    print(
        f"{action}：{summary['tripDays']} 个日期，"
        f"{summary['countries']} 个国家/地区，"
        f"{summary['featuredPhotos']} 张精选照片"
    )
    if not args.dry_run:
        print(
            f"增量导出：复用缓存 {stats.reused_photos} 张，"
            f"重新生成 {stats.generated_photos} 张"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
