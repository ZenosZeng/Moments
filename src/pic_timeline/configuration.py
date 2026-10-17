from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .photo_sources import PhotoSource, SOURCE_ID, validate_sources


class _ConfigLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        keys = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise yaml.constructor.ConstructorError(None, None, "配置键必须是文本", key_node.start_mark)
            if key in keys:
                raise yaml.constructor.ConstructorError(None, None, f"重复配置项：{key}", key_node.start_mark)
            keys.add(key)
        return super().construct_mapping(node, deep=deep)


@dataclass(frozen=True)
class SourceConfig:
    id: str
    path: Path | None
    parent: Path | None
    prefix: str
    legacy_paths: bool = False

    def resolve(self) -> PhotoSource:
        if self.path is not None:
            root = self.path
        else:
            if self.parent is None or not self.parent.is_dir():
                raise FileNotFoundError(f"照片源 {self.id} 的 parent 目录不存在")
            matches = sorted(p.resolve() for p in self.parent.iterdir() if p.is_dir() and p.name.startswith(self.prefix))
            if len(matches) != 1:
                raise ValueError(f"照片源 {self.id} 的 prefix 匹配到 {len(matches)} 个目录，请修改 config/local.yaml")
            root = matches[0]
        if not root.is_dir():
            raise FileNotFoundError(f"照片源 {self.id} 不存在：{root}")
        return PhotoSource(self.id, root.resolve(), self.legacy_paths)


@dataclass(frozen=True)
class LocalConfig:
    root: Path
    sources: tuple[SourceConfig, ...]
    host: str
    port: int
    index: Path
    annotations: Path
    thumbnails: Path
    exports: Path
    base_path: str
    compositions: Path

    def resolve_sources(self) -> list[PhotoSource]:
        sources = [source.resolve() for source in self.sources]
        validate_sources(sources)
        for source in sources:
            if self.root.is_relative_to(source.root) or source.root.is_relative_to(self.root):
                raise ValueError("原图必须位于 Moments 仓库外，避免扫描缓存或修改原图目录")
        return sources


def _keys(table: Any, allowed: set[str], label: str) -> dict[str, Any]:
    if not isinstance(table, dict) or table.keys() - allowed:
        raise ValueError(f"config/local.yaml 的 {label} 包含未知配置或格式无效")
    return table


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 必须是非空文本")
    return value.strip()


def _path(root: Path, value: Any, label: str) -> Path:
    path = Path(_text(value, label)).expanduser()
    return (root / path).resolve()


def validate_storage(root: Path, index: Path, annotations: Path, thumbnails: Path, exports: Path) -> None:
    data = root / "data"
    if data.resolve() != data:
        raise ValueError("data 不能链接到仓库外的目录")
    paths = (index, annotations, thumbnails, exports)
    if any(not p.is_relative_to(data) or p == data for p in paths):
        raise ValueError("数据库、缓存和导出路径必须位于仓库内被忽略的 data/ 子目录")
    if index == annotations or any(p.suffix not in {".sqlite3", ".sqlite", ".db"} for p in (index, annotations)):
        raise ValueError("索引和标注必须使用两个不同的 SQLite 文件")
    if thumbnails.is_relative_to(exports) or exports.is_relative_to(thumbnails):
        raise ValueError("缩略图缓存与导出目录不能互相包含")
    if any(p.is_relative_to(d) or d.is_relative_to(p) for p in (index, annotations) for d in (thumbnails, exports)):
        raise ValueError("数据库路径不能与缓存或导出目录重叠")
    if any(p.is_relative_to(root / "data" / "backups") for p in paths):
        raise ValueError("data/backups 仅用于备份，不能作为运行时数据路径")


def load_config(root: Path) -> LocalConfig:
    root = root.resolve()
    path = root / "config" / "local.yaml"
    if not path.is_file():
        raise FileNotFoundError("缺少 config/local.yaml；先执行 Copy-Item config/local.example.yaml config/local.yaml 并填写照片源")
    with path.open("r", encoding="utf-8-sig") as stream:
        try:
            raw = yaml.load(stream, Loader=_ConfigLoader)
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            position = f"（第 {mark.line + 1} 行，第 {mark.column + 1} 列）" if mark is not None else ""
            problem = getattr(exc, "problem", None) or "无法解析"
            raise ValueError(f"config/local.yaml 的 YAML 格式无效{position}：{problem}") from exc
    _keys(raw, {"photos", "app", "storage", "publish"}, "顶层")
    photos = _keys(raw.get("photos", {}), {"sources"}, "photos")
    entries = photos.get("sources")
    if not isinstance(entries, list) or not entries:
        raise ValueError("photos.sources 至少包含一个照片源")
    sources = []
    seen = set()
    for entry in entries:
        _keys(entry, {"id", "path", "parent", "prefix", "legacy_paths"}, "photos.sources")
        source_id = _text(entry.get("id"), "photos.sources.id")
        if not SOURCE_ID.fullmatch(source_id) or source_id in seen:
            raise ValueError("照片源 id 必须唯一，使用小写字母开头的字母、数字、下划线或连字符")
        seen.add(source_id)
        legacy_paths = entry.get("legacy_paths", False)
        if type(legacy_paths) is not bool:
            raise ValueError("legacy_paths 必须是 true 或 false")
        if "path" in entry:
            if "parent" in entry or "prefix" in entry:
                raise ValueError("照片源只能选择 path 或 parent + prefix，不能同时填写")
            sources.append(SourceConfig(source_id, _path(root, entry["path"], "照片源 path"), None, "", legacy_paths))
        else:
            sources.append(SourceConfig(source_id, None, _path(root, entry.get("parent"), "照片源 parent"), _text(entry.get("prefix"), "照片源 prefix"), legacy_paths))
    app = _keys(raw.get("app", {}), {"host", "port"}, "app")
    host = _text(app.get("host", "127.0.0.1"), "app.host")
    if host != "localhost":
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            raise ValueError("本地工具仅允许绑定 localhost 或回环地址")
    port = app.get("port", 8765)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("app.port 必须是 1 到 65535 的整数")
    storage = _keys(raw.get("storage", {}), {"index", "annotations", "thumbnails", "exports", "compositions"}, "storage")
    index = _path(root, storage.get("index", "data/db/photo_index.sqlite3"), "storage.index")
    annotations = _path(root, storage.get("annotations", "data/db/annotations.sqlite3"), "storage.annotations")
    thumbnails = _path(root, storage.get("thumbnails", "data/cache/thumbnails"), "storage.thumbnails")
    exports = _path(root, storage.get("exports", "data/exports"), "storage.exports")
    validate_storage(root, index, annotations, thumbnails, exports)
    compositions = _path(root, storage.get("compositions", "data/compositions"), "storage.compositions")
    data = root / "data"
    if not compositions.is_relative_to(data) or compositions == data or compositions.is_relative_to(data / "backups"):
        raise ValueError("图文组必须保存在 data/ 内独立的私密目录")
    if any(compositions.is_relative_to(path) or path.is_relative_to(compositions) for path in (index, annotations, thumbnails, exports)):
        raise ValueError("图文组目录不能与数据库、缓存或公开导出重叠")
    publish = _keys(raw.get("publish", {}), {"base_path"}, "publish")
    base = _text(publish.get("base_path", "/Moments/"), "publish.base_path")
    if not re.fullmatch(r"/(?:[A-Za-z0-9_-]+/)*", base):
        raise ValueError("publish.base_path 必须是 / 或 /仓库名/ 形式，不允许 URL、查询参数或路径穿越")
    return LocalConfig(root, tuple(sources), host, port, index, annotations, thumbnails, exports, base, compositions)
