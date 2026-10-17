"""Isolated synthetic workspace used only by the browser regression tests."""
from __future__ import annotations

import argparse
from collections.abc import Callable
import logging
import tempfile
import threading
from pathlib import Path

from PIL import Image, ImageDraw
from werkzeug.serving import make_server

from pic_timeline.analysis import scan_archive
from pic_timeline.compositions import photo_id
from pic_timeline.web import create_app


def demo_app(root: Path, shutdown: Callable | None = None):
    source = root / "synthetic-photos"
    month = source / "202405_a"
    month.mkdir(parents=True)
    for number in range(1, 13):
        image = Image.new("RGB", (960, 640), "#91c9df")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 320, 960, 640), fill="#4a8d79")
        draw.polygon(((0, 360), (260, 110 + number * 8), (550, 370)), fill="#608975")
        draw.polygon(((360, 380), (680, 180), (960, 380)), fill="#789c85")
        draw.ellipse((710, 65, 790, 145), fill="#f4dea1")
        draw.polygon(((280, 640), (490, 370), (550, 370), (600, 640)), fill="#e3d8b0")
        draw.rectangle((40 + number * 12, 390, 180 + number * 12, 470), fill=["#e8d2aa", "#d98d6f", "#d7e1c5"][number % 3])
        exif = Image.Exif()
        exif[36867] = f"2024:05:{2 if number <= 6 else 3:02d} 10:{number:02d}:00"
        image.save(month / f"scene-{number:02d}.jpg", quality=92, exif=exif)
    index = root / "data/db/index.sqlite3"
    scan_archive(source, index, refresh=True)
    app = create_app(index_path=index, annotation_path=root / "data/db/annotations.sqlite3",
                     thumbnail_root=root / "data/cache/thumbnails", source_finder=lambda: source,
                     composition_root=root / "data/compositions")
    if shutdown is not None:
        app.add_url_rule("/__test__/shutdown", view_func=shutdown, methods=["POST"])
    client = app.test_client()
    for day, start, city, place in (("02", 1, "深圳", "海边、公园、很长的滨海步道地点名称"), ("03", 7, "上海", "外滩、街巷")):
        result = client.put(f"/api/days/2024-05-{day}/annotation", json={
            "places": [{"city": city, "name": place}],
            "featuredPhotos": [{"relativePath": f"202405_a/scene-{number:02d}.jpg"} for number in range(start, start + 6)]})
        assert result.status_code == 200
    result = client.post("/api/compositions", json={
        "title": "海边与街巷的两日小记", "location": "滨海步道，街巷与公园", "captionTitle": "", "caption": "",
        "sourceDates": ["2024-05-02", "2024-05-03"],
        "photos": [{"id": photo_id(f"2024-05-{2 if number <= 6 else 3:02d}", f"202405_a/scene-{number:02d}.jpg"),
                    "captureDate": f"2024-05-{2 if number <= 6 else 3:02d}", "relativePath": f"202405_a/scene-{number:02d}.jpg",
                    "preset": "original", "strength": 100} for number in range(1, 9)]})
    assert result.status_code == 201
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18765)
    args = parser.parse_args()
    temporary_root = Path(__file__).resolve().parents[1] / ".pytest_tmp"
    temporary_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="composition-browser-", dir=temporary_root) as directory:
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        def shutdown():
            threading.Thread(target=server.shutdown, daemon=True).start()
            return {"stopping": True}

        with make_server("127.0.0.1", args.port, demo_app(Path(directory), shutdown), threaded=True) as server:
            server.serve_forever()
