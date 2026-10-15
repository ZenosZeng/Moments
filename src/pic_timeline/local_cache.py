from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable


CacheReport = Callable[[int, int, str], None]


def fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def jpeg_cache_path(root: Path, relative_path: str, record: dict[str, Any], variant: str) -> Path:
    key = f"{variant}|{relative_path}|{record['size']}|{record['mtime_ns']}"
    return root / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}.jpg"


def nonempty_file(path: Path) -> bool:
    try:
        return not path.is_symlink() and path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def valid_preview_entry(value: dict[str, Any]) -> bool:
    if set(value) != {"trip", "warnings", "paths", "cityKeys", "countryCodes"}:
        return False
    if any(not isinstance(value[key], list) or any(not isinstance(item, str) for item in value[key]) for key in ("warnings", "paths", "cityKeys", "countryCodes")):
        return False
    trip = value["trip"]
    if trip is None:
        return True
    if not isinstance(trip, dict) or set(trip) != {"id", "captureDate", "date", "year", "title", "places", "photos"}:
        return False
    if not isinstance(trip["places"], list) or not isinstance(trip["photos"], list):
        return False
    if any(not isinstance(trip[key], str) for key in ("id", "captureDate", "date", "title")) or type(trip["year"]) is not int:
        return False
    for place in trip["places"]:
        if not isinstance(place, dict) or set(place) != {"name", "city", "countryCode", "countryName", "mapPoint"}:
            return False
        if any(not isinstance(place[key], str) for key in ("name", "city", "countryCode", "countryName")):
            return False
        point = place["mapPoint"]
        if point is not None and (not isinstance(point, list) or len(point) != 2 or any(type(item) not in (int, float) for item in point)):
            return False
    return all(isinstance(photo, dict) and set(photo) == {"id", "src", "thumbnail"} and all(isinstance(item, str) for item in photo.values()) for photo in trip["photos"])


class JsonCache:
    def __init__(self, root: Path, version: int):
        self.root = root
        self.version = version

    def _path(self, key: str) -> Path:
        if self.root.is_symlink():
            raise ValueError("缓存目录不能是链接")
        return self.root / f"{fingerprint(key)}.json"

    def load(self, key: str, signature: str) -> dict[str, Any] | None:
        path = self._path(key)
        try:
            if path.is_symlink():
                return None
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("version") == self.version and value.get("signature") == signature and isinstance(value.get("data"), dict):
                return value["data"]
        except (OSError, ValueError, AttributeError):
            pass
        return None

    def save(self, key: str, signature: str, data: dict[str, Any]) -> None:
        path = self._path(key)
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.root, suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump({"version": self.version, "signature": signature, "data": data}, stream, ensure_ascii=False)
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


@contextmanager
def export_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".local-export.lock"
    if path.is_symlink():
        raise ValueError("导出锁不能是链接")
    with path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("另一个公开导出正在运行，请等待完成后重试") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
