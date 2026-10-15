from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from collections.abc import Mapping, Sequence
from contextlib import closing


SOURCE_ID = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
SOURCES_KEY = "photo_sources"


@dataclass(frozen=True)
class PhotoSource:
    id: str
    root: Path
    legacy_paths: bool = False


def validate_sources(sources: Sequence[PhotoSource]) -> None:
    if not sources:
        raise ValueError("至少配置一个原图目录")
    ids: set[str] = set()
    roots: list[Path] = []
    if sum(s.legacy_paths for s in sources) > 1:
        raise ValueError("最多一个照片源可以使用 legacy_paths")
    for source in sources:
        if not SOURCE_ID.fullmatch(source.id) or source.id in ids:
            raise ValueError("照片源 id 必须唯一，使用小写字母开头的字母、数字、下划线或连字符")
        root = source.root.resolve()
        if any(root.is_relative_to(other) or other.is_relative_to(root) for other in roots):
            raise ValueError("原图目录不能重复或互相包含")
        ids.add(source.id)
        roots.append(root)


def source_bindings(metadata: Mapping[str, str]) -> dict[str, dict[str, str]]:
    raw = metadata.get(SOURCES_KEY)
    if not raw:
        root = metadata.get("source_root")
        return {"legacy": {"root": root, "prefix": ""}} if root else {}
    bindings = json.loads(raw)
    if not isinstance(bindings, dict) or not bindings:
        raise ValueError("照片索引的多源配置无效")
    unprefixed = 0
    for source_id, binding in bindings.items():
        if not SOURCE_ID.fullmatch(source_id) or not isinstance(binding, dict):
            raise ValueError("照片索引的源 ID 无效")
        if not isinstance(binding.get("root"), str) or not binding["root"]:
            raise ValueError("照片索引缺少原图目录")
        prefix = binding.get("prefix")
        if prefix not in ("", f"{source_id}/"):
            raise ValueError("照片索引的路径前缀无效")
        unprefixed += prefix == ""
    if unprefixed > 1:
        raise ValueError("照片索引不能有多个兼容旧路径的源")
    return bindings


def register_sources(
    connection: sqlite3.Connection,
    sources: Sequence[PhotoSource],
    *,
    legacy_source_id: str | None = None,
) -> dict[str, dict[str, str]]:
    validate_sources(sources)
    metadata = dict(connection.execute("SELECT key, value FROM metadata"))
    if metadata.get(SOURCES_KEY):
        bindings = source_bindings(metadata)
    else:
        bindings = {}
        if connection.execute("SELECT COUNT(*) FROM photos").fetchone()[0]:
            matches = [s.id for s in sources if str(s.root.resolve()) == metadata.get("source_root")]
            selected = legacy_source_id or (matches[0] if len(matches) == 1 else None)
            if selected not in {s.id for s in sources}:
                raise ValueError("旧索引尚未指定原图来源，请先按迁移说明导入，不能猜测来源")
            if not next(s.legacy_paths for s in sources if s.id == selected):
                raise ValueError("旧照片源须在 config/local.yaml 设置 legacy_paths: true，确保重建索引后精选仍有效")
            # Preserve old selection keys and the IDs of generated image caches.
            bindings[selected] = {"root": "", "prefix": ""}
    for source in sources:
        prefix = "" if source.legacy_paths else f"{source.id}/"
        if source.id in bindings and bindings[source.id]["prefix"] != prefix:
            raise ValueError("已有照片源的 legacy_paths 不可修改，否则会改变精选引用")
        bindings[source.id] = {"root": str(source.root.resolve()), "prefix": prefix}
    connection.executemany(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
        [
            (SOURCES_KEY, json.dumps(bindings, ensure_ascii=False)),
            ("source_root", str(sources[0].root.resolve())),
            ("library_id", "multi-source-v1"),
        ],
    )
    return bindings


def bind_index_sources(index_path: Path, sources: Sequence[PhotoSource]) -> None:
    """Rebind renamed roots without scanning or changing photo/annotation keys."""
    validate_sources(sources)
    if not index_path.exists():
        return
    with closing(sqlite3.connect(index_path)) as connection, connection:
        connection.execute("PRAGMA busy_timeout = 5000")
        register_sources(connection, sources)


def binding_for_key(
    bindings: Mapping[str, dict[str, str]], relative_path: str
) -> tuple[str, dict[str, str], str]:
    for source_id, binding in bindings.items():
        if binding["prefix"] and relative_path.startswith(binding["prefix"]):
            return source_id, binding, relative_path[len(binding["prefix"]):]
    for source_id, binding in bindings.items():
        if not binding["prefix"]:
            return source_id, binding, relative_path
    raise ValueError("照片引用不属于已登记的原图来源")


def resolve_photo_path(metadata: Mapping[str, str], relative_path: str) -> Path:
    key = relative_path.replace("\\", "/")
    _, binding, local_path = binding_for_key(source_bindings(metadata), key)
    normalized = PurePosixPath(local_path)
    if not local_path or normalized.is_absolute() or ".." in normalized.parts or ":" in local_path:
        raise ValueError("照片包含不安全路径")
    root = Path(binding["root"]).resolve()
    path = root.joinpath(*normalized.parts).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise FileNotFoundError("原图不存在或路径超出照片源目录")
    return path
