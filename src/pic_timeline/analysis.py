from __future__ import annotations

import calendar
import os
import csv
import html
import json
import re
import sqlite3
import warnings
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import ExifTags, Image
from pillow_heif import register_heif_opener

from .photo_sources import PhotoSource, binding_for_key, register_sources, source_bindings
from .background_tasks import ProgressCallback
from .local_cache import CacheReport

register_heif_opener()

DEFAULT_SOURCE_PARENT = Path.home() / "Pictures"
DEFAULT_SOURCE_PREFIX = "photos"
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".heic", ".png"}
FOLDER_PATTERN = re.compile(r"^(?P<month>\d{6})_[A-Za-z0-9]+$")
LOCAL_ZONE_NAME = "Asia/Shanghai"
LOCAL_ZONE = ZoneInfo(LOCAL_ZONE_NAME)
EXIF_DATETIME_TAGS = (36867, 36868, 306)
EXIF_OFFSET_TAGS = (36881, 36882, 36880)


@dataclass(frozen=True)
class PhotoRecord:
    relative_path: str
    source_folder: str
    source_month: str
    extension: str
    size: int
    mtime_ns: int
    capture_time: str
    capture_date: str
    raw_capture_time: str
    date_source: str
    timezone_status: str
    month_matches: bool | None
    extraction_error: str

    @property
    def capture_datetime(self) -> datetime:
        if not self.capture_time:
            raise ValueError(f"Photo has no capture date: {self.relative_path}")
        return datetime.fromisoformat(self.capture_time)

    @property
    def is_metadata_date(self) -> bool:
        return self.date_source.startswith("exif:")


def find_source_root(
    parent: Path = DEFAULT_SOURCE_PARENT,
    prefix: str = DEFAULT_SOURCE_PREFIX,
) -> Path:
    """Find the unique archive directory whose name starts with the prefix."""
    configured = os.environ.get("MOMENTS_SOURCE")
    if configured and parent == DEFAULT_SOURCE_PARENT and prefix == DEFAULT_SOURCE_PREFIX:
        source = Path(configured).expanduser().resolve()
        if not source.is_dir():
            raise FileNotFoundError(f"Source directory does not exist: {source}")
        return source
    if not parent.is_dir():
        raise FileNotFoundError(f"Source parent directory does not exist: {parent}")
    matches = sorted(
        (
            child.resolve()
            for child in parent.iterdir()
            if child.is_dir() and child.name.startswith(prefix)
        ),
        key=lambda path: path.name.casefold(),
    )
    if not matches:
        raise FileNotFoundError(
            f"No source directory starting with {prefix!r} under: {parent}"
        )
    if len(matches) > 1:
        candidates = ", ".join(str(path) for path in matches)
        raise ValueError(
            f"Multiple source directories start with {prefix!r}; "
            f"use --source to choose one: {candidates}"
        )
    return matches[0]


def source_library_id(source_root: Path) -> str:
    """Return a stable identity that survives routine archive folder renames."""
    resolved = source_root.resolve()
    if resolved.name.startswith(DEFAULT_SOURCE_PREFIX):
        return f"prefix:{resolved.parent}|{DEFAULT_SOURCE_PREFIX}"
    return f"path:{resolved}"


def _get_exif_mapping(image: Image.Image) -> dict[int, object]:
    exif = image.getexif()
    values: dict[int, object] = dict(exif.items())
    try:
        exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
    except (AttributeError, KeyError, TypeError, ValueError):
        exif_ifd = {}
    values.update(exif_ifd)
    return values


def _decode_exif_value(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip("\x00 ")
    return str(value).strip("\x00 ")


def _parse_offset(value: str) -> ZoneInfo | None:
    if not re.fullmatch(r"[+-]\d{2}:\d{2}", value):
        return None
    sign = 1 if value[0] == "+" else -1
    hours = int(value[1:3])
    minutes = int(value[4:6])
    from datetime import timezone, timedelta

    return timezone(sign * timedelta(hours=hours, minutes=minutes))  # type: ignore[return-value]


def extract_capture_time(path: Path) -> tuple[datetime | None, str, str, str]:
    """Return local capture time, raw value, source field, and timezone status."""
    with warnings.catch_warnings():
        # The trusted local archive contains panoramas above Pillow's generic
        # pixel warning threshold; metadata extraction does not decode pixels.
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        with Image.open(path) as image:
            exif = _get_exif_mapping(image)

    raw_time = ""
    time_tag = 0
    for tag in EXIF_DATETIME_TAGS:
        value = exif.get(tag)
        if value:
            raw_time = _decode_exif_value(value)
            time_tag = tag
            break
    if not raw_time:
        return None, "", "", "missing"

    parsed = None
    for pattern in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(raw_time, pattern)
            break
        except ValueError:
            continue
    if parsed is None:
        raise ValueError(f"Unsupported EXIF date: {raw_time!r}")

    raw_offset = ""
    for tag in EXIF_OFFSET_TAGS:
        value = exif.get(tag)
        if value:
            raw_offset = _decode_exif_value(value)
            break
    offset_zone = _parse_offset(raw_offset) if raw_offset else None
    if offset_zone is not None:
        local_time = parsed.replace(tzinfo=offset_zone).astimezone(LOCAL_ZONE)
        timezone_status = f"metadata_offset:{raw_offset}"
    else:
        local_time = parsed.replace(tzinfo=LOCAL_ZONE)
        timezone_status = f"assumed:{LOCAL_ZONE_NAME}"
    return local_time, raw_time, f"exif:{time_tag}", timezone_status


def month_sequence(start_month: str, end_month: str) -> list[str]:
    start = datetime.strptime(start_month, "%Y%m")
    end = datetime.strptime(end_month, "%Y%m")
    if end < start:
        raise ValueError("end_month must not be earlier than start_month")
    result: list[str] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        result.append(f"{year:04d}{month:02d}")
        month = month + 1
        if month == 13:
            year, month = year + 1, 1
    return result


def _connect_index(
    index_path: Path,
    source_root: Path,
    *,
    sources: list[PhotoSource] | None = None,
) -> sqlite3.Connection:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(index_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS photos (
            relative_path TEXT PRIMARY KEY,
            source_folder TEXT NOT NULL,
            source_month TEXT NOT NULL,
            extension TEXT NOT NULL,
            size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            capture_time TEXT NOT NULL,
            capture_date TEXT NOT NULL DEFAULT '',
            raw_capture_time TEXT NOT NULL,
            date_source TEXT NOT NULL,
            timezone_status TEXT NOT NULL,
            month_matches INTEGER NOT NULL,
            extraction_error TEXT NOT NULL
        );
        """
    )
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(photos)")
    }
    if "capture_date" not in columns:
        connection.execute(
            "ALTER TABLE photos ADD COLUMN capture_date TEXT NOT NULL DEFAULT ''"
        )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_photos_capture_date
            ON photos(capture_date)
            WHERE capture_date <> ''
        """
    )
    source_key = str(source_root.resolve())
    library_id = source_library_id(source_root)
    schema_version = "3-stable-library-capture-date"
    current_library = connection.execute(
        "SELECT value FROM metadata WHERE key = 'library_id'"
    ).fetchone()
    current_schema = connection.execute(
        "SELECT value FROM metadata WHERE key = 'schema_version'"
    ).fetchone()
    if sources is not None:
        try:
            if current_schema is not None and current_schema["value"] != schema_version:
                raise ValueError("旧索引版本不兼容，请先备份并使用新的索引文件")
            register_sources(connection, sources)
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
                (schema_version,),
            )
            connection.commit()
            return connection
        except Exception:
            connection.close()
            raise
    if current_library is not None and current_library["value"] == "multi-source-v1":
        connection.close()
        raise ValueError("多源索引不能用单目录扫描，请使用 pixi run app 刷新索引")
    if (
        (current_library is not None and current_library["value"] != library_id)
        or current_schema is None
        or current_schema["value"] != schema_version
    ):
        connection.execute("DELETE FROM photos")
    connection.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES('source_root', ?)",
        (source_key,),
    )
    connection.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES('library_id', ?)",
        (library_id,),
    )
    connection.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
        (schema_version,),
    )
    connection.commit()
    return connection


def _row_to_record(row: sqlite3.Row) -> PhotoRecord:
    values = dict(row)
    stored_match = values["month_matches"]
    values["month_matches"] = None if stored_match == -1 else bool(stored_match)
    return PhotoRecord(**values)


def _upsert_record(connection: sqlite3.Connection, record: PhotoRecord) -> None:
    values = asdict(record)
    values["month_matches"] = (
        -1 if record.month_matches is None else int(record.month_matches)
    )
    connection.execute(
        """
        INSERT OR REPLACE INTO photos(
            relative_path, source_folder, source_month, extension, size,
            mtime_ns, capture_time, capture_date, raw_capture_time, date_source,
            timezone_status, month_matches, extraction_error
        ) VALUES(
            :relative_path, :source_folder, :source_month, :extension, :size,
            :mtime_ns, :capture_time, :capture_date, :raw_capture_time, :date_source,
            :timezone_status, :month_matches, :extraction_error
        )
        """,
        values,
    )


def scan_archive(
    source_root: Path,
    index_path: Path,
    *,
    refresh: bool = False,
    progress: ProgressCallback | None = None,
    cache_report: CacheReport | None = None,
) -> tuple[list[PhotoRecord], list[str], Counter[str]]:
    if not source_root.is_dir():
        raise FileNotFoundError(f"Source directory does not exist: {source_root}")
    connection = _connect_index(index_path, source_root)
    return _scan_bindings(
        connection,
        {"single": {"root": str(source_root.resolve()), "prefix": ""}},
        {"single"},
        refresh=refresh,
        progress=progress,
        cache_report=cache_report,
    )


def scan_sources(
    sources: list[PhotoSource],
    index_path: Path,
    *,
    refresh: bool = False,
    progress: ProgressCallback | None = None,
    cache_report: CacheReport | None = None,
) -> tuple[list[PhotoRecord], list[str], Counter[str]]:
    if not sources:
        raise ValueError("至少配置一个原图目录")
    connection = _connect_index(index_path, sources[0].root, sources=sources)
    metadata = dict(connection.execute("SELECT key, value FROM metadata"))
    return _scan_bindings(
        connection, source_bindings(metadata), {s.id for s in sources}, refresh=refresh, progress=progress, cache_report=cache_report
    )


def _scan_bindings(
    connection: sqlite3.Connection,
    bindings: dict[str, dict[str, str]],
    active_ids: set[str],
    *,
    refresh: bool,
    progress: ProgressCallback | None = None,
    cache_report: CacheReport | None = None,
) -> tuple[list[PhotoRecord], list[str], Counter[str]]:
    try:
        return _scan_bound_archives(connection, bindings, active_ids, refresh=refresh, progress=progress, cache_report=cache_report)
    finally:
        connection.close()


def _scan_bound_archives(
    connection: sqlite3.Connection,
    bindings: dict[str, dict[str, str]],
    active_ids: set[str],
    *,
    refresh: bool,
    progress: ProgressCallback | None = None,
    cache_report: CacheReport | None = None,
) -> tuple[list[PhotoRecord], list[str], Counter[str]]:
    month_folders: list[tuple[Path, str, Path, str]] = []
    for source_id, binding in bindings.items():
        if source_id not in active_ids:
            continue
        source_root = Path(binding["root"]).resolve()
        if not source_root.is_dir():
            raise FileNotFoundError(f"Source directory does not exist: {source_root}")
        source_months = []
        for folder in sorted(source_root.iterdir(), key=lambda item: item.name.lower()):
            match = FOLDER_PATTERN.match(folder.name) if folder.is_dir() else None
            if match:
                source_months.append((folder, match.group("month"), source_root, binding["prefix"]))
        if not source_months:
            raise ValueError(f"No monthly folders found under: {source_root}")
        month_folders.extend(source_months)
    inventory: list[tuple[Path, str, Path, str, list[Path]]] = []
    total_files = 0
    if progress:
        progress("扫描目录", 0, len(month_folders))
    for completed, (folder, source_month, source_root, prefix) in enumerate(month_folders, 1):
        files = sorted(
            (item for item in folder.rglob("*") if item.is_file() and item.suffix.lower() in PHOTO_EXTENSIONS),
            key=lambda item: str(item).lower(),
        )
        inventory.append((folder, source_month, source_root, prefix, files))
        total_files += len(files)
        if progress:
            progress("扫描目录", completed, len(month_folders))
    cached_rows = {row["relative_path"]: row for row in connection.execute("SELECT * FROM photos")}
    planned = {}
    reused = 0
    if progress:
        progress("检查照片缓存", 0, total_files)
    for folder, source_month, source_root, prefix, files in inventory:
        for path in files:
            if not path.resolve().is_relative_to(source_root):
                raise ValueError("原图中的链接不能指向照片源目录外")
            relative_path = prefix + path.relative_to(source_root).as_posix()
            stat = path.stat()
            cached = cached_rows.get(relative_path)
            if refresh or cached is None or cached["size"] != stat.st_size or cached["mtime_ns"] != stat.st_mtime_ns or cached["extraction_error"]:
                cached = None
            else:
                reused += 1
            planned[relative_path] = (stat, cached)
            if progress:
                progress("检查照片缓存", len(planned), total_files)
    if cache_report:
        cache_report(reused, total_files, "张照片")
    pending_files = total_files - reused
    records: list[PhotoRecord] = []
    seen: set[str] = set()
    counters: Counter[str] = Counter()
    try:
        if progress:
            progress("读取拍摄日期", 0, pending_files)
        for folder, source_month, source_root, prefix, files in inventory:
            for path in files:
                relative_path = prefix + path.relative_to(source_root).as_posix()
                seen.add(relative_path)
                stat, cached = planned[relative_path]
                if (
                    not refresh
                    and cached is not None
                    and cached["size"] == stat.st_size
                    and cached["mtime_ns"] == stat.st_mtime_ns
                ):
                    record = _row_to_record(cached)
                    counters["cached"] += 1
                else:
                    extraction_error = ""
                    try:
                        capture_time, raw_time, date_source, timezone_status = (
                            extract_capture_time(path)
                        )
                    except Exception as exc:  # keep a malformed file from aborting a scan
                        capture_time = None
                        raw_time = ""
                        date_source = ""
                        timezone_status = "missing"
                        extraction_error = f"{type(exc).__name__}: {exc}"
                        counters["errors"] += 1
                    if capture_time is None:
                        capture_iso = ""
                        capture_date = ""
                        date_source = "missing"
                        timezone_status = "missing"
                        month_matches = None
                        counters["missing_date"] += 1
                    else:
                        capture_iso = capture_time.isoformat(timespec="seconds")
                        capture_date = capture_time.date().isoformat()
                        month_matches = capture_time.strftime("%Y%m") == source_month
                        counters["metadata"] += 1
                    record = PhotoRecord(
                        relative_path=relative_path,
                        source_folder=folder.name,
                        source_month=source_month,
                        extension=path.suffix.lower(),
                        size=stat.st_size,
                        mtime_ns=stat.st_mtime_ns,
                        capture_time=capture_iso,
                        capture_date=capture_date,
                        raw_capture_time=raw_time,
                        date_source=date_source,
                        timezone_status=timezone_status,
                        month_matches=month_matches,
                        extraction_error=extraction_error,
                    )
                    _upsert_record(connection, record)
                    counters["scanned"] += 1
                records.append(record)
                if progress and cached is None:
                    progress("读取拍摄日期", counters["scanned"], pending_files)
                if len(records) % 1000 == 0:
                    print(f"Indexed {len(records)} photos...", flush=True)
            connection.commit()

        if progress:
            progress("整理索引", 0, 1)
        stale_rows = connection.execute("SELECT relative_path FROM photos").fetchall()
        stale = [
            row["relative_path"] for row in stale_rows
            if binding_for_key(bindings, row["relative_path"])[0] in active_ids
            and row["relative_path"] not in seen
        ]
        if stale:
            connection.executemany(
                "DELETE FROM photos WHERE relative_path = ?",
                ((path,) for path in stale),
            )
            counters["removed_from_index"] = len(stale)
        connection.commit()
        if progress:
            progress("整理索引", 1, 1)
    except Exception:
        connection.rollback()
        raise

    source_months = sorted({month for _, month, _, _ in month_folders})
    return records, source_months, counters


def _write_csv(path: Path, rows: Iterable[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _configure_chinese_font() -> None:
    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def _render_chart(
    path: Path,
    month: str,
    confirmed: list[int],
) -> None:
    _configure_chinese_font()
    year, month_number = int(month[:4]), int(month[4:])
    days = list(range(1, len(confirmed) + 1))
    total = confirmed

    figure, axis = plt.subplots(figsize=(14, 7.2), dpi=140)
    figure.patch.set_facecolor("#f7f7f5")
    axis.set_facecolor("#ffffff")
    axis.bar(days, confirmed, color="#287271", width=0.78, label="已确认拍摄时间")
    axis.set_title(
        f"{year} 年 {month_number:02d} 月每日照片数量",
        fontsize=20,
        pad=18,
    )
    axis.set_xlabel("日期（日）", fontsize=12)
    axis.set_ylabel("照片数量", fontsize=12)
    axis.set_xticks(days)
    axis.set_xlim(0.3, len(days) + 0.7)
    axis.set_ylim(0, max(1, max(total, default=0) * 1.18))
    axis.grid(axis="y", color="#d9d9d9", linewidth=0.8, alpha=0.8)
    axis.set_axisbelow(True)
    axis.spines[["top", "right"]].set_visible(False)
    axis.legend(frameon=False, loc="upper right")
    axis.text(
        0.01,
        0.97,
        f"纳入统计 {sum(total)} 张；缺少拍摄日期的图片不参与统计",
        transform=axis.transAxes,
        va="top",
        fontsize=10,
        color="#333333",
    )
    for day, count in zip(days, total, strict=True):
        if count:
            axis.text(day, count, str(count), ha="center", va="bottom", fontsize=7)
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, format="png", bbox_inches="tight")
    plt.close(figure)


def _build_month_rows(
    records: list[PhotoRecord], source_months: list[str]
) -> tuple[list[dict[str, object]], dict[str, list[int]]]:
    dated_records = [record for record in records if record.is_metadata_date]
    capture_months = [record.capture_datetime.strftime("%Y%m") for record in dated_records]
    all_known_months = source_months + capture_months
    months = month_sequence(min(all_known_months), max(all_known_months))
    grouped: dict[str, list[int]] = {}
    source_folder_map: dict[str, set[str]] = defaultdict(set)
    for record in records:
        source_folder_map[record.source_month].add(record.source_folder)

    by_month: dict[str, list[PhotoRecord]] = defaultdict(list)
    for record in dated_records:
        by_month[record.capture_datetime.strftime("%Y%m")].append(record)
    missing_by_source_month = Counter(
        record.source_month for record in records if not record.is_metadata_date
    )

    rows: list[dict[str, object]] = []
    for month in months:
        year, month_number = int(month[:4]), int(month[4:])
        day_count = calendar.monthrange(year, month_number)[1]
        confirmed = [0] * day_count
        month_records = by_month.get(month, [])
        for record in month_records:
            day = record.capture_datetime.day
            confirmed[day - 1] += 1
        grouped[month] = confirmed
        rows.append(
            {
                "month": f"{month[:4]}-{month[4:]}",
                "days": day_count,
                "included_photos": sum(confirmed),
                "excluded_missing_date": missing_by_source_month[month],
                "source_folders": ";".join(sorted(source_folder_map.get(month, set()))),
                "month_mismatches": sum(
                    1
                    for record in dated_records
                    if record.source_month == month and record.month_matches is False
                ),
            }
        )
    return rows, grouped


def _write_html_report(
    output_root: Path,
    month_rows: list[dict[str, object]],
    summary: dict[str, object],
) -> Path:
    cards = []
    for row in month_rows:
        month_label = str(row["month"])
        filename = f"charts/{month_label}.png"
        cards.append(
            "<section><h2>{month}</h2>"
            "<p>纳入统计 {included} 张；缺少拍摄日期、未纳入 {excluded} 张</p>"
            '<img loading="lazy" src="{src}" alt="{month} 每日照片数量图表"></section>'.format(
                month=html.escape(month_label),
                included=row["included_photos"],
                excluded=row["excluded_missing_date"],
                src=html.escape(filename),
            )
        )
    summary_json = html.escape(json.dumps(summary, ensure_ascii=False, indent=2))
    content = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>照片时间线月度报告</title>
  <style>
    body {{ margin: 0; color: #222; background: #f4f4f1; font-family: "Microsoft YaHei", sans-serif; }}
    header {{ padding: 28px max(24px, calc((100% - 1200px) / 2)); background: #fff; border-bottom: 1px solid #ddd; }}
    main {{ max-width: 1200px; margin: 0 auto; padding: 28px 24px 60px; }}
    section {{ margin: 0 0 36px; padding: 20px; background: #fff; border: 1px solid #ddd; border-radius: 6px; }}
    h1, h2 {{ margin-top: 0; }}
    img {{ display: block; width: 100%; height: auto; }}
    pre {{ overflow: auto; padding: 16px; background: #f6f6f3; }}
  </style>
</head>
<body>
  <header><h1>照片时间线月度报告</h1><p>每月一张图，横轴为日期，纵轴为当天照片数量。</p></header>
  <main><pre>{summary_json}</pre>{''.join(cards)}</main>
</body>
</html>
"""
    report_path = output_root / "index.html"
    report_path.write_text(content, encoding="utf-8")
    return report_path


def analyze_archive(
    source_root: Path,
    output_root: Path,
    index_path: Path,
    *,
    refresh: bool = False,
) -> dict[str, object]:
    records, source_months, scan_counters = scan_archive(
        source_root, index_path, refresh=refresh
    )
    month_rows, grouped = _build_month_rows(records, source_months)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "fallback_photos.csv").unlink(missing_ok=True)
    charts_root = output_root / "charts"
    charts_root.mkdir(parents=True, exist_ok=True)

    for month, confirmed in grouped.items():
        _render_chart(
            charts_root / f"{month[:4]}-{month[4:]}.png",
            month,
            confirmed,
        )

    _write_csv(
        output_root / "monthly_summary.csv",
        month_rows,
        [
            "month",
            "days",
            "included_photos",
            "excluded_missing_date",
            "source_folders",
            "month_mismatches",
        ],
    )
    missing_date_rows = [asdict(record) for record in records if not record.is_metadata_date]
    mismatch_rows = [
        asdict(record) for record in records if record.month_matches is False
    ]
    error_rows = [asdict(record) for record in records if record.extraction_error]
    record_fields = list(asdict(records[0]).keys()) if records else list(PhotoRecord.__annotations__)
    _write_csv(
        output_root / "missing_capture_dates.csv", missing_date_rows, record_fields
    )
    _write_csv(output_root / "month_mismatches.csv", mismatch_rows, record_fields)
    _write_csv(output_root / "extraction_errors.csv", error_rows, record_fields)

    summary: dict[str, object] = {
        "source_root": str(source_root.resolve()),
        "photo_count": len(records),
        "included_count": sum(record.is_metadata_date for record in records),
        "missing_date_count": len(missing_date_rows),
        "mismatch_count": len(mismatch_rows),
        "error_count": len(error_rows),
        "chart_count": len(grouped),
        "scan_counters": dict(scan_counters),
    }
    report_path = _write_html_report(output_root, month_rows, summary)
    summary["report_path"] = str(report_path.resolve())
    (output_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary
