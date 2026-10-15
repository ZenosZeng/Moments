from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from typing import Callable
import zipfile


MEDIA_NAME = re.compile(r"media/[0-9a-f]{20}(?:-thumb)?\.webp\Z")
MAX_FILES = 50_000
MAX_BYTES = 2 * 1024**3
PRIVATE_IDENTITY_FIELDS = {
    "people", "person", "personId", "person_id", "companion", "companions",
    "publicName", "public_name", "privateName", "private_name",
}
PRIVATE_PATH_FIELDS = {
    "sourceRoot", "source_root", "sourceRoots", "source_roots",
    "photoSources", "photo_sources",
}


def check_private_identity_fields(value: object) -> None:
    if isinstance(value, list):
        for child in value:
            check_private_identity_fields(child)
    elif isinstance(value, dict):
        for key, child in value.items():
            if key in PRIVATE_IDENTITY_FIELDS | PRIVATE_PATH_FIELDS:
                raise ValueError(f"公开 JSON 包含禁止字段：{key}")
            check_private_identity_fields(child)


def _allowed_file(name: str) -> bool:
    return name == "data/trips.json" or MEDIA_NAME.fullmatch(name) is not None


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pack_public_data(source: Path, output: Path, *, progress: Callable[[str, int, int], None] | None = None) -> Path:
    source = source.resolve()
    data = source / "data"
    media = source / "media"
    for directory in (data, media):
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError(f"公开数据包缺少有效目录：{directory.name}")
    if sorted(path.name for path in data.iterdir()) != ["trips.json"]:
        raise ValueError("公开数据的 data/ 只能包含 trips.json")
    files = [data / "trips.json", *sorted(media.iterdir())]
    for path in files:
        name = path.relative_to(source).as_posix()
        if path.is_symlink() or not path.is_file() or not _allowed_file(name):
            raise ValueError(f"公开数据包含非白名单文件：{name}")
    check_private_identity_fields(json.loads((data / "trips.json").read_text(encoding="utf-8")))
    if len(files) > MAX_FILES or sum(path.stat().st_size for path in files) >= MAX_BYTES:
        raise ValueError("公开数据包超过文件数或 2 GiB 限制")
    output = output.absolute()
    if output.is_symlink() or output.with_name(output.name + ".sha256").is_symlink():
        raise ValueError("公开 ZIP 或校验文件不能是链接")
    output = output.parent.resolve() / output.name
    if output == data / "trips.json" or output.is_relative_to(media):
        raise ValueError("ZIP 输出不能覆盖公开数据")
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(dir=output.parent, suffix=".zip.tmp")
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        if progress:
            progress("打包公开数据", 0, len(files))
        with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
            for completed, path in enumerate(files, 1):
                # WebP is already compressed; storing it avoids redundant compression.
                compression = zipfile.ZIP_STORED if path.suffix == ".webp" else zipfile.ZIP_DEFLATED
                archive.write(path, path.relative_to(source).as_posix(), compress_type=compression)
                if progress:
                    progress("打包公开数据", completed, len(files))
        if temporary.stat().st_size >= MAX_BYTES:
            raise ValueError("ZIP 附件必须小于 2 GiB")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    checksum = output.with_name(output.name + ".sha256")
    if progress:
        progress("计算校验和", 0, 1)
    temporary_checksum = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="ascii", dir=output.parent, suffix=".sha256.tmp", delete=False) as stream:
            temporary_checksum = Path(stream.name)
            stream.write(f"{_sha256(output)}  {output.name}\n")
        temporary_checksum.replace(checksum)
    finally:
        if temporary_checksum is not None:
            temporary_checksum.unlink(missing_ok=True)
    if progress:
        progress("计算校验和", 1, 1)
    return checksum


def extract_public_data(archive_path: Path, output: Path, checksum: Path | None = None) -> None:
    if checksum is not None:
        tokens = checksum.read_text(encoding="ascii").split()
        if not tokens or not re.fullmatch(r"[0-9a-f]{64}", tokens[0]):
            raise ValueError("无效的 SHA-256 校验文件")
        if _sha256(archive_path) != tokens[0]:
            raise ValueError("公开 ZIP 的 SHA-256 校验失败")
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("解压目录必须不存在，避免覆盖已有数据")
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_FILES or sum(entry.file_size for entry in entries) >= MAX_BYTES:
            raise ValueError("公开 ZIP 超过文件数或解压大小限制")
        names: set[str] = set()
        for entry in entries:
            name = entry.filename
            if name in names:
                raise ValueError(f"公开 ZIP 包含重复文件：{name}")
            names.add(name)
            if stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                raise ValueError(f"公开 ZIP 不允许链接或加密文件：{name}")
            if entry.is_dir():
                if name not in {"data/", "media/"}:
                    raise ValueError(f"公开 ZIP 包含非白名单目录：{name}")
            elif not _allowed_file(name):
                raise ValueError(f"公开 ZIP 包含非白名单文件：{name}")
        if "data/trips.json" not in names:
            raise ValueError("公开 ZIP 缺少 data/trips.json")
        output.mkdir(parents=True)
        try:
            (output / "data").mkdir()
            (output / "media").mkdir()
            for entry in entries:
                if entry.is_dir():
                    continue
                with archive.open(entry) as source, (output / entry.filename).open("wb") as target:
                    shutil.copyfileobj(source, target)
            check_private_identity_fields(
                json.loads((output / "data" / "trips.json").read_text(encoding="utf-8"))
            )
        except Exception:
            # This directory was created by this operation and only contains whitelisted files.
            shutil.rmtree(output)
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description="白名单公开数据 ZIP 打包与安全解压")
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("pack")
    pack.add_argument("source", type=Path)
    pack.add_argument("output", type=Path)
    extract = commands.add_parser("extract")
    extract.add_argument("archive", type=Path)
    extract.add_argument("output", type=Path)
    extract.add_argument("--sha256", type=Path)
    args = parser.parse_args()
    if args.command == "pack":
        checksum = pack_public_data(args.source, args.output)
        print(f"公开 ZIP 和校验文件已生成：{args.output.name}、{checksum.name}")
    else:
        extract_public_data(args.archive, args.output, args.sha256)
        print("公开 ZIP 校验和解压完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
