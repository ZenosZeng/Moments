"""One-time local migration; never starts the app, exports, deletes, or uploads."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image
from pic_timeline.configuration import load_config
from pic_timeline.photo_sources import register_sources, resolve_photo_path


EXCLUDED = {
    "node_modules", ".pixi", "dist", "__pycache__", ".pytest_cache", ".pytest_tmp",
    ".mypy_cache", ".ruff_cache", ".agents", "_tmp", ".runtime_tmp",
}
PHOTO_ID = re.compile(r"^[a-f0-9]{20}$")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def progress(stage: str, current: int, total: int) -> None:
    interval = max(1, total // 10)
    if current in (0, total) or current % interval == 0:
        print(f"{stage}：{current}/{total}", flush=True)


def backup_database(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"旧数据库不存在：{source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src:
        src.execute("PRAGMA query_only = ON")
        with closing(sqlite3.connect(destination)) as target:
            src.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("迁移数据库完整性检查失败")
            if target.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ValueError("迁移数据库存在无效外键")


def table_fingerprints(path: Path) -> dict[str, dict[str, object]]:
    result = {}
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        for table in tables:
            if table in {"metadata", "people", "day_people"}:
                continue
            quoted = '"' + table.replace('"', '""') + '"'
            where = " WHERE key <> 'migration_vienna_companion_v1'" if table == "app_settings" else ""
            rows = sorted(connection.execute(f"SELECT * FROM {quoted}{where}").fetchall(), key=repr)
            payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            result[table] = {"rows": len(rows), "sha256": hashlib.sha256(payload).hexdigest()}
    return result


def copy_verified(source: Path, target: Path) -> None:
    if source.is_symlink():
        raise ValueError("迁移不接受指向其他目录的链接")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if digest(source) != digest(target):
        raise ValueError("复制文件的 SHA-256 校验失败")


def copy_thumbnails(source: Path, target: Path) -> int:
    files = sorted(source.glob("*.jpg")) if source.is_dir() else []
    progress("迁移本地缩略图", 0, len(files))
    for number, path in enumerate(files, 1):
        if not re.fullmatch(r"[a-f0-9]{64}\.jpg", path.name):
            raise ValueError("缩略图缓存含有非缓存文件")
        copy_verified(path, target / path.name)
        progress("迁移本地缩略图", number, len(files))
    target.mkdir(parents=True, exist_ok=True)
    return len(files)


def clean_webp(path: Path, limit: tuple[int, int]) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    try:
        with Image.open(path) as image:
            if image.format != "WEBP" or image.getexif() or image.info.get("exif") or image.info.get("xmp"):
                return False
            if image.width > limit[0] or image.height > limit[1]:
                return False
            image.verify()
        return True
    except (OSError, ValueError, SyntaxError):
        return False


def copy_media_cache(roots: list[Path], target: Path) -> int:
    ids = sorted({p.stem for root in roots if root.is_dir() for p in root.glob("*.webp") if PHOTO_ID.fullmatch(p.stem)})
    progress("迁移脱敏图片缓存", 0, len(ids))
    copied = 0
    for number, photo_id in enumerate(ids, 1):
        for root in roots:
            full, thumb = root / f"{photo_id}.webp", root / f"{photo_id}-thumb.webp"
            if clean_webp(full, (1920, 1440)) and clean_webp(thumb, (640, 480)):
                copy_verified(full, target / full.name)
                copy_verified(thumb, target / thumb.name)
                copied += 1
                break
        progress("迁移脱敏图片缓存", number, len(ids))
    target.mkdir(parents=True, exist_ok=True)
    return copied


def archive_repository(source: Path, archive_root: Path, stamp: str) -> dict[str, object]:
    source = source.resolve()
    if not (source / ".git").is_dir() or source == ROOT or not source.is_relative_to(ROOT.parent):
        raise ValueError("只允许归档 Moments 同工作区内的旧 Git 仓库")
    if archive_root.resolve() != ROOT / "_archive":
        raise ValueError("归档目录必须是 Moments 内的 _archive，不能链接到其他位置")
    files = []
    for directory, names, filenames in os.walk(source, followlinks=False):
        folder = Path(directory)
        kept = []
        for name in sorted(names):
            path = folder / name
            if name in EXCLUDED or name.startswith((".public-export-", ".public-import-")):
                continue
            if path.parent == source / "data" and name.startswith("edge-"):
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(source):
                raise ValueError("归档目录包含链接，拒绝读取仓库外文件")
            kept.append(name)
        names[:] = kept
        for name in sorted(filenames):
            path = folder / name
            if path.is_symlink() or not path.resolve().is_relative_to(source):
                raise ValueError("归档文件包含链接")
            if name.endswith((".pyc", ".pyo", ".log")):
                continue
            files.append(path)
    archive_root.mkdir(parents=True, exist_ok=True)
    target = archive_root / f"{source.name}-{stamp}.zip"
    temporary = target.with_suffix(".zip.partial")
    if target.exists() or temporary.exists():
        raise FileExistsError("归档名称已存在，不覆盖既有归档")
    progress(f"归档 {source.name}", 0, len(files))
    with zipfile.ZipFile(temporary, "w", allowZip64=True, compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for number, path in enumerate(files, 1):
            before = path.stat()
            compression = zipfile.ZIP_STORED if path.suffix.lower() in {".jpg", ".png", ".webp", ".heic", ".zip", ".pack"} else zipfile.ZIP_DEFLATED
            archive.write(path, f"{source.name}/{path.relative_to(source).as_posix()}", compress_type=compression)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError("归档期间旧文件发生变化，请关闭旧应用后重试")
            progress(f"归档 {source.name}", number, len(files))
    print(f"校验归档 {source.name} 的全部 ZIP 条目…", flush=True)
    with zipfile.ZipFile(temporary) as archive:
        if archive.testzip() is not None or len(archive.namelist()) != len(files):
            raise ValueError("ZIP 内容校验失败")
    checksum = digest(temporary)
    temporary.rename(target)
    target.with_suffix(".zip.sha256").write_text(f"{checksum}  {target.name}\n", encoding="ascii")
    return {"file": target.name, "files": len(files), "bytes": target.stat().st_size, "sha256": checksum}


def migrate(studio: Path, public: Path, legacy_source: str) -> dict[str, object]:
    config = load_config(ROOT)
    sources = config.resolve_sources()
    if legacy_source not in {s.id for s in sources}:
        raise ValueError("legacy-source 必须对应 config/local.yaml 中的一个照片源 ID")
    if not next(s.legacy_paths for s in sources if s.id == legacy_source):
        raise ValueError("旧照片源需先配置 legacy_paths: true，避免重建索引时丢失旧精选引用")
    targets = [config.index, config.annotations, config.thumbnails, config.exports]
    if any(p.exists() for p in targets):
        raise FileExistsError("目标数据库、缓存或导出目录已经存在，拒绝覆盖；请先检查或另行备份")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backups = ROOT / "data" / "backups"
    if not backups.resolve().is_relative_to(ROOT / "data"):
        raise ValueError("备份目录不能链接到仓库外")
    backups.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".legacy-import-", dir=backups) as temporary:
        stage = Path(temporary)
        snapshots = stage / "original"
        for name in ("annotations.sqlite3", "photo_index.sqlite3"):
            print(f"一致性备份：{name}", flush=True)
            backup_database(studio / "data" / name, snapshots / name)
            backup_database(snapshots / name, stage / "db" / name)
        annotation = stage / "db" / "annotations.sqlite3"
        index = stage / "db" / "photo_index.sqlite3"
        with closing(sqlite3.connect(annotation)) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA secure_delete = ON")
            connection.execute("DROP TABLE IF EXISTS day_people")
            connection.execute("DROP TABLE IF EXISTS people")
            connection.execute("DELETE FROM app_settings WHERE key = 'migration_vienna_companion_v1'")
            connection.commit()
            connection.execute("VACUUM")
        with closing(sqlite3.connect(index)) as connection:
            register_sources(connection, sources, legacy_source_id=legacy_source)
            connection.commit()
            metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        for name in ("annotations.sqlite3", "photo_index.sqlite3"):
            if table_fingerprints(snapshots / name) != table_fingerprints(stage / "db" / name):
                raise ValueError("迁移后有效数据的逐表校验不一致")
        with closing(sqlite3.connect(annotation)) as ann, closing(sqlite3.connect(index)) as idx:
            featured = ann.execute("SELECT capture_date,relative_path FROM day_featured_photos").fetchall()
            for day, key in featured:
                row = idx.execute("SELECT capture_date,size,mtime_ns FROM photos WHERE relative_path=?", (key,)).fetchone()
                stat = resolve_photo_path(metadata, key).stat()
                if row is None or row != (day, stat.st_size, stat.st_mtime_ns):
                    raise ValueError("旧精选引用与当前原图不匹配，未安装迁移结果")
            counts = {"annotationDays": ann.execute("SELECT COUNT(*) FROM day_annotations").fetchone()[0], "featuredPhotos": len(featured), "indexedPhotos": idx.execute("SELECT COUNT(*) FROM photos").fetchone()[0]}
        thumbnails = copy_thumbnails(studio / "data" / "thumbnails", stage / "thumbnails")
        media = copy_media_cache([studio / "exports" / "moment-trails-public" / "media", public / "public" / "media"], stage / "public-data" / "media")
        (stage / "public-data" / ".media-cache-version").write_text("1\n", encoding="ascii")
        for path in (studio / "data").glob("annotations-before-*.sqlite3"):
            backup_database(path, snapshots / path.name)
        archives = [archive_repository(path, ROOT / "_archive", stamp) for path in (studio, public)]
        for name in ("annotations.sqlite3", "photo_index.sqlite3"):
            if table_fingerprints(studio / "data" / name) != table_fingerprints(snapshots / name):
                raise ValueError("迁移期间旧数据库发生变化，拒绝安装旧快照")
        for path in (annotation, index):
            with closing(sqlite3.connect(path)) as connection:
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise ValueError("最终数据库校验失败")
        config.index.parent.mkdir(parents=True, exist_ok=True)
        config.annotations.parent.mkdir(parents=True, exist_ok=True)
        config.thumbnails.parent.mkdir(parents=True, exist_ok=True)
        config.exports.mkdir(parents=True, exist_ok=True)
        index.rename(config.index)
        annotation.rename(config.annotations)
        (stage / "thumbnails").rename(config.thumbnails)
        (stage / "public-data").rename(config.exports / "public-data")
        snapshot_target = backups / f"legacy-{stamp}"
        snapshots.rename(snapshot_target)
        report = {"createdAt": datetime.now().isoformat(timespec="seconds"), **counts, "thumbnails": thumbnails, "cachedPhotos": media, "archives": archives, "tables": {"annotations": table_fingerprints(config.annotations), "index": table_fingerprints(config.index)}, "originalDirectoriesRetained": True}
        (snapshot_target / "migration.local.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({**counts, "thumbnails": thumbnails, "cachedPhotos": media, "archives": [a["file"] for a in archives]}, ensure_ascii=False, indent=2), flush=True)
        print("迁移完成；原图和旧目录未修改或删除，旧 JSON 未放入当前导出。", flush=True)
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移旧数据并生成私密 ZIP 归档，不运行或发布网站")
    parser.add_argument("--studio", type=Path, required=True)
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--legacy-source", required=True, help="旧索引归属的固定照片源 ID")
    args = parser.parse_args()
    migrate(args.studio.resolve(), args.public.resolve(), args.legacy_source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
