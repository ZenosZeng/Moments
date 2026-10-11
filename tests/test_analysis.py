from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

from pic_timeline.analysis import (
    analyze_archive,
    extract_capture_time,
    find_source_root,
    month_sequence,
    scan_archive,
)


LOCAL_ZONE = ZoneInfo("Asia/Shanghai")


def _write_jpeg(path: Path, date_text: str | None, offset: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (12, 8), "#287271")
    exif = Image.Exif()
    if date_text:
        exif[36867] = date_text
    if offset:
        exif[36881] = offset
    image.save(path, exif=exif)


def test_month_sequence_crosses_year_and_keeps_leap_month() -> None:
    assert month_sequence("202312", "202403") == [
        "202312",
        "202401",
        "202402",
        "202403",
    ]


def test_find_source_root_by_prefix(tmp_path: Path) -> None:
    expected = tmp_path / "photos 2016-2026.01"
    expected.mkdir()
    (tmp_path / "other").mkdir()

    assert find_source_root(tmp_path, "photos") == expected.resolve()


def test_find_source_root_rejects_ambiguous_matches(tmp_path: Path) -> None:
    (tmp_path / "photos archive-a").mkdir()
    (tmp_path / "photos archive-b").mkdir()

    try:
        find_source_root(tmp_path, "photos")
    except ValueError as exc:
        assert "Multiple source directories" in str(exc)
    else:
        raise AssertionError("Expected ambiguous source directories to fail")


def test_archive_root_rename_reuses_cached_index(tmp_path: Path) -> None:
    parent = tmp_path / "archives"
    first_root = parent / "photos 2024.01"
    photo = first_root / "202401_a" / "one.jpg"
    _write_jpeg(photo, "2024:01:05 12:00:00")
    index = tmp_path / "index.sqlite3"

    first_records, _, first_counters = scan_archive(first_root, index)
    second_root = parent / "photos 2024.02"
    first_root.rename(second_root)
    second_records, _, second_counters = scan_archive(second_root, index)

    assert first_records[0].capture_date == "2024-01-05"
    assert first_counters["scanned"] == 1
    assert second_records[0].capture_date == "2024-01-05"
    assert second_counters["cached"] == 1


def test_extract_capture_time_uses_exif_offset(tmp_path: Path) -> None:
    photo = tmp_path / "photo.jpg"
    _write_jpeg(photo, "2024:02:03 10:20:30", "+08:00")

    captured, raw, source, timezone_status = extract_capture_time(photo)

    assert captured == datetime(2024, 2, 3, 10, 20, 30, tzinfo=LOCAL_ZONE)
    assert raw == "2024:02:03 10:20:30"
    assert source == "exif:36867"
    assert timezone_status == "metadata_offset:+08:00"


def test_extract_capture_time_from_heic(tmp_path: Path) -> None:
    photo = tmp_path / "photo.heic"
    image = Image.new("RGB", (12, 8), "#e9c46a")
    exif = Image.Exif()
    exif[36867] = "2024:03:04 11:22:33"
    image.save(photo, format="HEIF", exif=exif)

    captured, raw, source, timezone_status = extract_capture_time(photo)

    assert captured == datetime(2024, 3, 4, 11, 22, 33, tzinfo=LOCAL_ZONE)
    assert raw == "2024:03:04 11:22:33"
    assert source == "exif:36867"
    assert timezone_status == "assumed:Asia/Shanghai"


def test_scan_excludes_missing_dates_without_mtime_fallback(tmp_path: Path) -> None:
    source = tmp_path / "source"
    month = source / "202402_a"
    dated = month / "dated.jpg"
    missing_date = month / "missing-date.png"
    ignored = month / "clip.mov"
    _write_jpeg(dated, "2024:02:03 10:20:30")
    Image.new("RGB", (8, 8), "white").save(missing_date)
    ignored.write_bytes(b"not a real video")
    fallback_time = datetime(2024, 2, 4, 8, 0, tzinfo=LOCAL_ZONE).timestamp()
    os.utime(missing_date, (fallback_time, fallback_time))

    records, months, counters = scan_archive(
        source, tmp_path / "index.sqlite3", refresh=True
    )

    assert months == ["202402"]
    assert len(records) == 2
    by_name = {Path(record.relative_path).name: record for record in records}
    assert by_name["dated.jpg"].date_source == "exif:36867"
    assert by_name["dated.jpg"].capture_date == "2024-02-03"
    assert by_name["dated.jpg"].month_matches is True
    assert by_name["missing-date.png"].date_source == "missing"
    assert by_name["missing-date.png"].capture_time == ""
    assert by_name["missing-date.png"].capture_date == ""
    assert by_name["missing-date.png"].month_matches is None
    assert counters["metadata"] == 1
    assert counters["missing_date"] == 1


def test_report_generates_one_png_per_calendar_month(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_jpeg(source / "202401_a" / "one.jpg", "2024:01:05 12:00:00")
    _write_jpeg(source / "202403_a" / "two.jpg", "2024:03:08 13:00:00")
    output = tmp_path / "report"

    result = analyze_archive(
        source,
        output,
        tmp_path / "index.sqlite3",
        refresh=True,
    )

    assert result["chart_count"] == 3
    for month in ("2024-01", "2024-02", "2024-03"):
        chart = output / "charts" / f"{month}.png"
        assert chart.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert (output / "index.html").exists()
    with (output / "monthly_summary.csv").open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["month"] for row in rows] == ["2024-01", "2024-02", "2024-03"]
    assert rows[1]["included_photos"] == "0"


def test_report_does_not_count_photo_without_capture_date(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_jpeg(source / "202405_a" / "dated.jpg", "2024:05:02 12:00:00")
    missing = source / "202405_a" / "missing.png"
    Image.new("RGB", (8, 8), "white").save(missing)

    output = tmp_path / "report"
    output.mkdir()
    (output / "fallback_photos.csv").write_text("legacy", encoding="utf-8")
    result = analyze_archive(
        source,
        output,
        tmp_path / "index.sqlite3",
        refresh=True,
    )

    assert result["photo_count"] == 2
    assert result["included_count"] == 1
    assert result["missing_date_count"] == 1
    assert not (output / "fallback_photos.csv").exists()
    with (output / "monthly_summary.csv").open(encoding="utf-8-sig") as handle:
        row = next(csv.DictReader(handle))
    assert row["included_photos"] == "1"
    assert row["excluded_missing_date"] == "1"
