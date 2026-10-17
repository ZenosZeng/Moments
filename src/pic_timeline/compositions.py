from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from flask import Blueprint, abort, jsonify, request, send_file
from PIL import Image, ImageEnhance, ImageOps


FILTER_RECIPES = [
    {"id": "original", "name": "原色", "brightness": 1, "contrast": 1, "color": 1, "warmth": 0, "fade": 0},
    {"id": "clear", "name": "清透日常", "brightness": 1.06, "contrast": 1.06, "color": 1.08, "warmth": 0, "fade": 0},
    {"id": "warm-film", "name": "暖调胶片", "brightness": 1.03, "contrast": .96, "color": .91, "warmth": 10, "fade": 7},
    {"id": "cool-city", "name": "冷调城市", "brightness": 1.01, "contrast": 1.12, "color": .87, "warmth": -9, "fade": 2},
    {"id": "soft-fade", "name": "柔雾复古", "brightness": 1.04, "contrast": .87, "color": .81, "warmth": 4, "fade": 14},
    {"id": "vivid", "name": "鲜活风景", "brightness": 1.02, "contrast": 1.1, "color": 1.2, "warmth": 2, "fade": 0},
    {"id": "mono", "name": "黑白纪实", "brightness": 1.02, "contrast": 1.14, "color": 0, "warmth": 0, "fade": 3},
    {"id": "sunset", "name": "落日暖金", "brightness": 1.04, "contrast": 1.08, "color": 1.12, "warmth": 14, "fade": 3},
    {"id": "forest", "name": "森系青绿", "brightness": 1.01, "contrast": .97, "color": .92, "warmth": -2, "fade": 6, "tint": (-3, 6, -2)},
    {"id": "ocean", "name": "海盐蓝调", "brightness": 1.06, "contrast": .97, "color": 1.06, "warmth": -4, "fade": 4, "tint": (-4, 3, 6)},
    {"id": "cream", "name": "奶油柔光", "brightness": 1.08, "contrast": .86, "color": .85, "warmth": 6, "fade": 11},
    {"id": "peach", "name": "蜜桃暖粉", "brightness": 1.04, "contrast": .94, "color": .9, "warmth": 3, "fade": 6, "tint": (6, -2, 4)},
    {"id": "retro", "name": "复古棕调", "brightness": .98, "contrast": 1.03, "color": .72, "warmth": 13, "fade": 12},
    {"id": "cinema", "name": "青橙电影", "brightness": .99, "contrast": 1.2, "color": .93, "warmth": 0, "fade": 3, "split": 12},
    {"id": "matte", "name": "哑光留白", "brightness": 1.01, "contrast": .92, "color": .65, "warmth": 0, "fade": 19},
    {"id": "airy", "name": "明亮通透", "brightness": 1.14, "contrast": .93, "color": 1.02, "warmth": 1, "fade": 4},
    {"id": "night", "name": "夜景冷光", "brightness": 1.08, "contrast": 1.18, "color": .82, "warmth": -11, "fade": 0, "tint": (0, -3, 3)},
    {"id": "soft-mono", "name": "柔雾黑白", "brightness": 1.06, "contrast": .85, "color": 0, "warmth": 0, "fade": 15},
    {"id": "hard-mono", "name": "高反差黑白", "brightness": .99, "contrast": 1.38, "color": 0, "warmth": 0, "fade": 0},
    {"id": "neutral", "name": "自然纪实", "brightness": 1.01, "contrast": 1.04, "color": .95, "warmth": 0, "fade": 1},
]
PRESET_MAP = {preset["id"]: preset for preset in FILTER_RECIPES}
# Keep retired recipes readable without crowding the nine-tile picker.
PRESETS = [PRESET_MAP[key] for key in (
    "original", "clear", "warm-film", "cool-city", "soft-fade", "vivid", "mono", "forest", "cinema",
)]
GROUP_ID = re.compile(r"[a-f0-9]{32}")
PHOTO_ID = re.compile(r"[a-f0-9]{24}")
LEGACY_ASSET_NAME = re.compile(r"[a-f0-9]{24}-[a-f0-9]{20}\.jpg")
ASSET_NAME = re.compile(r"(?:[a-f0-9]{24}-[a-f0-9]{20}|\d{2,}_\d{4}-\d{2}-\d{2}_v\d{4,}|\d{4}-\d{2}-\d{2}_\d{2,}_底图_v\d{4,})\.jpg")


class CompositionConflict(ValueError):
    pass


def photo_id(capture_date: str, relative_path: str) -> str:
    return hashlib.sha256(f"{capture_date}|{relative_path}".encode()).hexdigest()[:24]


def parse_date(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("日期格式无效")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("日期格式无效") from exc
    if parsed.isoformat() != value:
        raise ValueError("日期必须使用 YYYY-MM-DD")
    return value


def creation_day(created_at: str) -> str:
    return datetime.fromisoformat(created_at).astimezone().date().isoformat()


def next_publish_date(start: str, occupied: set[str]) -> str:
    candidate = date.fromisoformat(parse_date(start))
    while candidate.isoformat() in occupied:
        try:
            candidate += timedelta(days=1)
        except OverflowError as exc:
            raise ValueError("没有可用的计划发布日期") from exc
    return candidate.isoformat()


def filter_settings(preset: Any = "original", strength: Any = 100) -> tuple[str, int]:
    if not isinstance(preset, str) or preset not in PRESET_MAP:
        raise ValueError("未知滤镜")
    if isinstance(strength, str) and re.fullmatch(r"\d{1,3}", strength):
        strength = int(strength)
    if type(strength) is not int or not 0 <= strength <= 100:
        raise ValueError("滤镜强度必须是 0 到 100 的整数")
    return preset, strength


def apply_filter(image: Image.Image, preset: str, strength: int) -> Image.Image:
    preset, strength = filter_settings(preset, strength)
    original = ImageOps.exif_transpose(image).convert("RGB")
    settings = PRESET_MAP[preset]
    result = ImageEnhance.Brightness(original).enhance(settings["brightness"])
    result = ImageEnhance.Contrast(result).enhance(settings["contrast"])
    result = ImageEnhance.Color(result).enhance(settings["color"])
    warmth, fade = settings["warmth"], settings["fade"]
    channels = result.split()
    tint = settings.get("tint", (0, 0, 0))
    shifts = tuple(base + extra for base, extra in zip((warmth, 0, -warmth), tint))
    result = Image.merge("RGB", tuple(
        channel.point([round(max(0, min(255, value * (1 - fade / 255) + fade + shift))) for value in range(256)])
        for channel, shift in zip(channels, shifts)
    ))
    if settings.get("split"):
        # Cool shadows and warm highlights, blended by image luminance.
        mask = ImageOps.grayscale(result)
        shadow = Image.new("RGB", result.size, (19, 83, 91))
        highlight = Image.new("RGB", result.size, (239, 180, 112))
        tone = Image.composite(highlight, shadow, mask)
        result = Image.blend(result, tone, settings["split"] / 100)
    return Image.blend(original, result, strength / 100)


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _jpeg(path: Path, image: Image.Image) -> None:
    temporary = None
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            # A new pixel-only image deliberately discards EXIF, GPS, XMP and comments.
            clean = Image.new("RGB", image.size)
            clean.paste(image.convert("RGB"))
            clean.save(stream, "JPEG", quality=94, optimize=True)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class CompositionStore:
    def __init__(self, root: Path, annotations: Any, photo_index: Any, base_photo: Callable):
        self.root = root.resolve()
        self.annotations = annotations
        self.photo_index = photo_index
        self.base_photo = base_photo
        self.lock = threading.RLock()
        self._folders: dict[str, Path] = {}

    def _refresh_folders(self) -> None:
        if self.root.resolve() != self.root:
            raise ValueError("图文目录不可使用链接")
        folders = {}
        for folder in self.root.iterdir() if self.root.is_dir() else []:
            if folder.name.startswith(".") or not folder.is_dir():
                continue
            manifest = folder / "group.json"
            if not manifest.is_file():
                continue
            if folder.resolve() != folder or manifest.resolve() != manifest:
                raise ValueError("图文目录和清单不可使用链接")
            try:
                group_id = json.loads(manifest.read_bytes())["id"]
                if not isinstance(group_id, str) or not GROUP_ID.fullmatch(group_id):
                    raise ValueError()
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError("图文组文件格式无效，请检查 group.json") from exc
            if group_id in folders:
                raise ValueError("图文组ID重复，请检查是否复制了整个目录")
            folders[group_id] = folder
        self._folders = folders

    def folder(self, group_id: str) -> Path:
        if not GROUP_ID.fullmatch(group_id):
            abort(404)
        if group_id not in self._folders or not self._folders[group_id].is_dir():
            self._refresh_folders()
        folder = self._folders.get(group_id, self.root / group_id)
        if folder.resolve() != folder or self.root.resolve() != self.root:
            raise ValueError("图文目录不可使用链接")
        return folder

    def readable_folder(self, time: dict, cities: list[str], title: str) -> Path:
        def component(text: str, limit: int) -> str:
            text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
            return re.sub(r"\s+", " ", text).strip(" ._")[:limit].rstrip(" .") or "未命名"

        period = time["start"] if time["start"] == time["end"] else f"{time['start']}至{time['end']}"
        name = f"{period}_{component('、'.join(cities) or '未标注城市', 24)}_{component(title, 40)}"
        folder = self.root / name
        number = 2
        while folder.exists() or folder.is_symlink():
            folder = self.root / f"{name}_{number}"
            number += 1
        if self.root.resolve() != self.root:
            raise ValueError("图文目录不可使用链接")
        return folder

    def asset(self, group: dict, filename: str, kind: str = "images") -> Path:
        if kind not in {"base", "images"} or not ASSET_NAME.fullmatch(filename):
            abort(404)
        key = "baseFile" if kind == "base" else "file"
        if not any(photo.get(key) == f"{kind}/{filename}" for photo in group["photos"]):
            abort(404)
        path = self.folder(group["id"]) / kind / filename
        if path.resolve() != path or not path.is_file():
            abort(404)
        return path

    def _read_group(self, group_id: str) -> dict:
        path = self.folder(group_id) / "group.json"
        if not path.is_file():
            abort(404)
        if path.resolve() != path:
            raise ValueError("图文清单不可使用链接")
        try:
            raw = path.read_bytes()
            group = json.loads(raw)
            if group["schemaVersion"] != 1 or group["id"] != group_id or not isinstance(group["photos"], list):
                raise ValueError()
            if any(not PHOTO_ID.fullmatch(photo["id"]) for photo in group["photos"]):
                raise ValueError()
            if "publishDate" in group:
                parse_date(group["publishDate"])
            if type(group.get("autoPublishDate", True)) is not bool:
                raise ValueError()
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError("图文组文件格式无效，请检查 group.json") from exc
        group["etag"] = hashlib.sha256(raw).hexdigest()
        return group

    def get(self, group_id: str) -> dict:
        with self.lock:
            group = self._read_group(group_id)
            if "publishDate" not in group:
                return next(item for item in self.list() if item["id"] == group_id)
            group.setdefault("autoPublishDate", True)
            return group

    def list(self) -> list[dict]:
        with self.lock:
            self._refresh_folders()
            groups = [self._read_group(group_id) for group_id in self._folders]
            occupied = {group["publishDate"] for group in groups if "publishDate" in group}
            # Old v1 manifests get deterministic suggestions without rewriting private files on read.
            for group in sorted(groups, key=lambda item: (item["createdAt"], item["id"])):
                if "publishDate" not in group:
                    group["publishDate"] = next_publish_date(creation_day(group["createdAt"]), occupied)
                    occupied.add(group["publishDate"])
                group.setdefault("autoPublishDate", True)
            return sorted(groups, key=lambda group: group["updatedAt"], reverse=True)

    def sync_caption(self, group: dict) -> None:
        with self.lock:
            if self.get(group["id"])["etag"] != group["etag"]:
                return
            path = self.folder(group["id"]) / "文案.txt"
            if path.resolve() != path:
                raise ValueError("文案文件不可使用链接")
            text = f"{group['captionTitle'] or group['title']}\n\n{group['caption']}\n".encode("utf-8")
            if not path.is_file() or path.read_bytes() != text:
                _atomic_bytes(path, text)

    def source_day(self, capture_date: str) -> dict:
        annotation = self.annotations.get(parse_date(capture_date))
        paths = [photo["relativePath"] for photo in annotation["featuredPhotos"]]
        records = self.photo_index.photos_by_paths(paths)
        photos = []
        for path in paths:
            if records.get(path, {}).get("capture_date") != capture_date:
                continue
            query = urlencode({"date": capture_date, "path": path})
            photos.append({"id": photo_id(capture_date, path), "captureDate": capture_date,
                           "relativePath": path, "thumbnail": f"/api/compositions/source-image?{query}&size=thumb",
                           "src": f"/api/compositions/source-image?{query}"})
        return {"captureDate": capture_date, "date": annotation["displayDate"],
                "cities": list(dict.fromkeys(place["city"] for place in annotation["places"] if place["city"])),
                "places": list(dict.fromkeys(place["name"] for place in annotation["places"] if place["name"])),
                "photos": photos}

    def source_dates(self) -> list[dict]:
        return [{"captureDate": item["date"], "date": item["displayDate"],
                 "cities": list(dict.fromkeys(place["city"] for place in item["places"] if place["city"])),
                 "places": list(dict.fromkeys(place["name"] for place in item["places"] if place["name"])),
                 "count": len(item["featuredPhotos"])}
                for item in reversed(self.annotations.all()) if item["featuredPhotos"]]

    def checked_source(self, capture_date: str, relative_path: str) -> dict:
        day = self.source_day(capture_date)
        if not any(photo["relativePath"] == relative_path for photo in day["photos"]):
            raise ValueError("只能选择所选日期中已经精选的照片")
        return day

    def save(self, payload: Any, group_id: str | None = None) -> dict:
        with self.lock:
            return self._save(payload, group_id)

    def _save(self, payload: Any, group_id: str | None) -> dict:
        if not isinstance(payload, dict) or payload.keys() - {"title", "location", "captionTitle", "caption", "sourceDates", "photos", "etag", "autoFill", "time", "cities", "publishDate", "autoPublishDate"}:
            raise ValueError("图文组参数无效")
        old = self.get(group_id) if group_id else None
        if old and payload.get("etag") != old["etag"]:
            raise CompositionConflict("图文组已被其他页面或 Agent 修改，请重新载入后保存")
        fields = {}
        for key, label, limit in (("title", "标题", 140), ("location", "地点", 300), ("captionTitle", "文案标题", 140), ("caption", "文案", 20000)):
            value = payload.get(key, "")
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError(f"{label}格式无效或超出长度限制")
            fields[key] = value.strip()
        if not fields["title"] or not fields["location"]:
            raise ValueError("标题和地点必填")
        dates = payload.get("sourceDates")
        selected = payload.get("photos")
        if not isinstance(dates, list) or not dates or len(dates) > 1000:
            raise ValueError("至少选择一个日期")
        dates = sorted(set(parse_date(day) for day in dates))
        if not isinstance(selected, list) or not selected or len(selected) > 1000:
            raise ValueError("至少选择一张精选照片，最多 1000 张")
        old_days = {day["captureDate"]: day for day in old["days"]} if old else {}
        days = {}
        for day in dates:
            current = self.source_day(day)
            if current["photos"]:
                days[day] = {key: current[key] for key in ("captureDate", "date", "cities", "places")}
            elif day in old_days:
                days[day] = old_days[day]
            else:
                raise ValueError("所选日期没有可用的精选照片")
        auto_fill = payload.get("autoFill", (old or {}).get("autoFill", {"time": True, "cities": True}))
        if not isinstance(auto_fill, dict) or set(auto_fill) != {"time", "cities"} or any(type(value) is not bool for value in auto_fill.values()):
            raise ValueError("自动填写设置必须包含时间和城市两个勾选值")
        display_dates = sorted(set(day["date"] for day in days.values()))
        display_time = {"start": display_dates[0], "end": display_dates[-1], "dates": display_dates}
        display_cities = list(dict.fromkeys(city for day in days.values() for city in day["cities"]))
        if not auto_fill["time"]:
            manual = payload.get("time") if "time" in payload else {key: (old or {}).get("time", {}).get(key) for key in ("start", "end")}
            if not isinstance(manual, dict) or manual.keys() - {"start", "end"}:
                raise ValueError("手动时间需提供开始和结束日期")
            start, end = parse_date(manual.get("start")), parse_date(manual.get("end"))
            if start > end:
                raise ValueError("结束日期不能早于开始日期")
            display_time = {"start": start, "end": end, "dates": sorted({start, end})}
        elif "time" in payload:
            raise ValueError("请先取消时间的自动填写，再手动修改")
        if not auto_fill["cities"]:
            manual = payload.get("cities", (old or {}).get("cities", []))
            if not isinstance(manual, list) or len(manual) > 100 or any(not isinstance(city, str) or len(city) > 100 for city in manual):
                raise ValueError("手动城市格式无效")
            display_cities = list(dict.fromkeys(city.strip() for city in manual if city.strip()))
        elif "cities" in payload:
            raise ValueError("请先取消城市的自动填写，再手动修改")
        created_at = old["createdAt"] if old else datetime.now(timezone.utc).isoformat(timespec="microseconds")
        auto_publish = payload.get("autoPublishDate", (old or {}).get("autoPublishDate", True))
        if type(auto_publish) is not bool:
            raise ValueError("计划发布日期的自动填写设置必须为勾选值")
        if auto_publish:
            if "publishDate" in payload:
                raise ValueError("请先取消计划发布日期的自动填写，再手动修改")
            if old and old["autoPublishDate"]:
                publish_date = old["publishDate"]
            else:
                occupied = {group["publishDate"] for group in self.list() if group["id"] != group_id}
                publish_date = next_publish_date(creation_day(created_at), occupied)
        else:
            publish_date = parse_date(payload.get("publishDate", (old or {}).get("publishDate")))
        group_id = group_id or uuid.uuid4().hex
        folder = self.folder(group_id) if old else self.readable_folder(display_time, display_cities, fields["title"])
        self._folders[group_id] = folder
        revision = old["revision"] + 1 if old else 1
        for kind in ("base", "images"):
            if (folder / kind).resolve() != folder / kind:
                raise ValueError("图文图片目录不可使用链接")
        previous = {photo["id"]: photo for photo in old["photos"]} if old else {}
        prepared, seen = [], set()
        for photo in selected:
            if not isinstance(photo, dict) or photo.keys() - {"id", "captureDate", "relativePath", "preset", "strength"}:
                raise ValueError("图片参数无效")
            capture = parse_date(photo.get("captureDate"))
            relative = photo.get("relativePath")
            if not isinstance(relative, str) or not relative or "\\" in relative or relative.startswith("/") or any(part in {"", ".", ".."} for part in relative.split("/")) or ":" in relative:
                raise ValueError("图片引用必须为安全的相对路径")
            key = photo_id(capture, relative)
            if capture not in dates or key in seen or photo.get("id") != key:
                raise ValueError("图片重复、标识无效或不属于所选日期")
            seen.add(key)
            preset, strength = filter_settings(photo.get("preset", "original"), photo.get("strength", 100))
            prior = previous.get(key)
            if prior:
                base = self.asset(old, Path(prior["baseFile"]).name, "base")
            else:
                self.checked_source(capture, relative)
                base = self.base_photo(relative, max_size=(2400, 2400), quality=94, variant="composition-base-v1")
            prepared.append((key, capture, relative, preset, strength, base, prior))
        photos = []
        for number, (key, capture, relative, preset, strength, source, prior) in enumerate(prepared, 1):
            base_file = prior["baseFile"] if prior and not LEGACY_ASSET_NAME.fullmatch(Path(prior["baseFile"]).name) else f"base/{capture}_{number:04d}_底图_v{revision:04d}.jpg"
            destination = folder / base_file
            if destination.resolve() != destination:
                raise ValueError("图文底图不可使用链接")
            if source != destination:
                _atomic_bytes(destination, source.read_bytes())
            image_file = f"images/{number:04d}_{capture}_v{revision:04d}.jpg"
            if (folder / image_file).resolve() != folder / image_file:
                raise ValueError("图文图片不可使用链接")
            if prior and prior["filter"] == {"version": 1, "preset": preset, "strength": strength} and (folder / prior["file"]).is_file():
                previous_image = self.asset(old, Path(prior["file"]).name)
                _atomic_bytes(folder / image_file, previous_image.read_bytes())
            else:
                with Image.open(destination) as image:
                    _jpeg(folder / image_file, apply_filter(image, preset, strength))
            photos.append({"id": key, "captureDate": capture, "relativePath": relative,
                           "baseFile": base_file, "file": image_file,
                           "filter": {"version": 1, "preset": preset, "strength": strength}})
        now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        group = {"schemaVersion": 1, "id": group_id, "revision": revision,
                 "createdAt": created_at, "updatedAt": now, **fields,
                 "publishDate": publish_date, "autoPublishDate": auto_publish,
                 "sourceDates": dates, "days": list(days.values()),
                 "time": display_time, "cities": display_cities, "autoFill": auto_fill, "photos": photos}
        if old and self.get(group_id)["etag"] != old["etag"]:
            raise CompositionConflict("图文组在生成图片期间已变化，请重新载入")
        if folder.name == group_id:
            readable = self.readable_folder(display_time, display_cities, fields["title"])
            try:
                folder.rename(readable)
            except PermissionError as exc:
                raise ValueError("旧图文目录正被占用，本次未保存；请关闭目录中的图片后重试") from exc
            self._folders[group_id] = folder = readable
        _atomic_bytes(folder / "group.json", (json.dumps(group, ensure_ascii=False, indent=2) + "\n").encode())
        # The manifest is the commit point. Never remove photos referenced by the previous revision before it.
        retained = {item[key] for item in photos for key in ("file", "baseFile")}
        for kind in ("base", "images"):
            for asset in (folder / kind).glob("*.jpg"):
                if f"{kind}/{asset.name}" not in retained and ASSET_NAME.fullmatch(asset.name):
                    try:
                        asset.unlink()
                    except PermissionError:
                        pass
        (folder / "agent-request.md").unlink(missing_ok=True)
        return self.get(group_id)

    def render(self, source: Path, preset: str, strength: int, size: str) -> Path:
        preset, strength = filter_settings(preset, strength)
        if size not in {"thumb", "preview"}:
            raise ValueError("图片尺寸无效")
        stat = source.stat()
        key = hashlib.sha256(f"{source}|{stat.st_mtime_ns}|{stat.st_size}|{preset}|{strength}|{size}|1".encode()).hexdigest()
        cache = self.root.parent / "cache" / "compositions" / f"{key}.jpg"
        with self.lock:
            if not cache.is_file():
                with Image.open(source) as image:
                    result = apply_filter(image, preset, strength)
                    result.thumbnail((400, 400) if size == "thumb" else (2000, 2000))
                    _jpeg(cache, result)
        return cache

    def agent_request(self, group_id: str, etag: str) -> dict:
        with self.lock:
            group = self.get(group_id)
            if etag != group["etag"]:
                raise CompositionConflict("图文组已变化，请重新载入")
            images = "\n".join(f"{number}. `{photo['file']}`" for number, photo in enumerate(group["photos"], 1))
            text = (
                "# 图文组文案任务\n\n"
                "此文件只准备任务，不调用任何模型、不上传图片、不自动发布。\n\n"
                "读取同目录 group.json 与下列图片，写一篇真实简洁的地点分享。\n"
                "仅修改 group.json 的 captionTitle 和 caption（UTF-8 JSON），其他字段及图片不得修改。\n"
                "已有文案不应未经确认覆盖；不要编造票价、营业时间、人物、经历或图片中无法确认的事实。\n"
                "保留拍摄时间背景，不读取原图、其他日期、数据库或路径配置，不上传任何文件。\n\n"
                f"图文标题：{group['title']}\n地点：{group['location']}\n"
                f"日期：{group['time']['start']} 至 {group['time']['end']}\n城市：{', '.join(group['cities'])}\n\n"
                f"## 图片顺序\n\n{images}\n"
            )
            _atomic_bytes(self.folder(group_id) / "agent-request.md", text.encode())
            return {"directory": self.folder(group_id).as_posix(), "requestFile": "agent-request.md",
                    "prompt": f"请读取 {self.folder(group_id).as_posix()}/agent-request.md，按其中要求处理这个图文组。"}


def register_compositions(app, annotations, photo_index, base_photo, root: Path) -> None:
    store = CompositionStore(root, annotations, photo_index, base_photo)
    bp = Blueprint("compositions", __name__, url_prefix="/api/compositions")

    @bp.errorhandler(CompositionConflict)
    def conflict(error):
        return jsonify({"error": str(error), "code": "COMPOSITION_CONFLICT"}), 409

    def response_group(group):
        store.sync_caption(group)
        result = {**group, "directory": store.folder(group["id"]).as_posix()}
        result["photos"] = [{**photo, "thumbnail": f"/api/compositions/{group['id']}/photo/{photo['id']}?size=thumb&preset={photo['filter']['preset']}&strength={photo['filter']['strength']}",
                             "src": f"/api/compositions/{group['id']}/photo/{photo['id']}?preset={photo['filter']['preset']}&strength={photo['filter']['strength']}"} for photo in group["photos"]]
        return result

    @bp.get("")
    def listing():
        return jsonify({"groups": [response_group(group) for group in store.list()]})

    @bp.get("/sources")
    def sources():
        return jsonify({"dates": store.source_dates(), "presets": [{"id": p["id"], "name": p["name"]} for p in PRESETS],
                        "presetNames": {key: preset["name"] for key, preset in PRESET_MAP.items()}})

    @bp.get("/sources/<capture_date>")
    def source_day(capture_date):
        return jsonify(store.source_day(capture_date))

    @bp.get("/source-image")
    def source_image():
        capture, relative = request.args.get("date", ""), request.args.get("path", "")
        store.checked_source(capture, relative)
        source = base_photo(relative, max_size=(2400, 2400), quality=94, variant="composition-base-v1")
        preset, strength = filter_settings(request.args.get("preset", "original"), request.args.get("strength", "100"))
        return send_file(store.render(source, preset, strength, request.args.get("size", "preview")), mimetype="image/jpeg", conditional=True)

    @bp.post("")
    def create():
        return jsonify(response_group(store.save(request.get_json(silent=True)))), 201

    @bp.get("/<group_id>")
    def get(group_id):
        return jsonify(response_group(store.get(group_id)))

    @bp.put("/<group_id>")
    def update(group_id):
        return jsonify(response_group(store.save(request.get_json(silent=True), group_id)))

    @bp.delete("/<group_id>")
    def delete(group_id):
        with store.lock:
            group = store.get(group_id)
            payload = request.get_json(silent=True) or {}
            if payload.get("etag") != group["etag"]:
                raise CompositionConflict("图文组已变化，请重新载入")
            # Local trash allows recovery; never delete original photos or annotations.
            trash = store.root / ".trash"
            if trash.resolve() != trash:
                raise ValueError("图文回收目录不可使用链接")
            trash.mkdir(parents=True, exist_ok=True)
            folder = store.folder(group_id)
            folder.rename(trash / f"{folder.name}_删除于{datetime.now(timezone.utc):%Y%m%d-%H%M%S-%f}")
        return jsonify({"deleted": True})

    @bp.get("/<group_id>/photo/<image_id>")
    def photo(group_id, image_id):
        group = store.get(group_id)
        selected = next((photo for photo in group["photos"] if photo["id"] == image_id), None)
        if selected is None:
            abort(404)
        source = store.asset(group, Path(selected["baseFile"]).name, "base")
        preset, strength = filter_settings(request.args.get("preset", selected["filter"]["preset"]), request.args.get("strength", str(selected["filter"]["strength"])))
        return send_file(store.render(source, preset, strength, request.args.get("size", "preview")), mimetype="image/jpeg", conditional=True)

    @bp.post("/<group_id>/agent-request")
    def agent_request(group_id):
        payload = request.get_json(silent=True) or {}
        return jsonify(store.agent_request(group_id, payload.get("etag", "")))

    app.register_blueprint(bp)
    app.extensions["composition_store"] = store
