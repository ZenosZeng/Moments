from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from typing import Any

from .background_tasks import ProgressCallback
from .local_cache import CacheReport, export_lock
from .photo_sources import source_bindings
from .public_package import pack_public_data


ARTIFACTS = ("public-data.zip", "public-data.zip.sha256")
EXPORT_PHASES = {
    "读取导出快照": (0, .03), "扫描图片缓存": (.03, .12),
    "复用缓存图片": (.12, .17), "生成新增图片": (.17, .78),
    "审计临时导出": (.78, .85), "替换本地导出": (.85, .87),
    "复核最终导出": (.87, .93), "打包公开数据": (.93, .98),
    "计算校验和": (.98, .99),
}


def release_data(
    index: Path, annotations: Path, output: Path,
    progress: ProgressCallback, cache_report: CacheReport,
) -> dict[str, Any]:
    # The exporter uses web.AnnotationStore; defer importing until the app is initialized.
    from .export_public import ExportStats, export_public

    index, annotations = index.resolve(), annotations.resolve()
    with closing(sqlite3.connect(index.as_uri() + "?mode=ro", uri=True)) as connection:
        bindings = source_bindings(dict(connection.execute("SELECT key,value FROM metadata")))
    output = output.resolve()
    if any(output.is_relative_to(Path(item["root"]).resolve()) or Path(item["root"]).resolve().is_relative_to(output) for item in bindings.values()):
        raise ValueError("公开产物目录不能与原图目录重叠")
    with export_lock(output), tempfile.TemporaryDirectory(prefix=".private-export-", dir=output) as temporary:
        stage = Path(temporary)
        progress("读取导出快照", 0, 2)
        for completed, (original, name) in enumerate(((index, "index.sqlite3"), (annotations, "annotations.sqlite3")), 1):
            with closing(sqlite3.connect(original.as_uri() + "?mode=ro", uri=True)) as source, closing(sqlite3.connect(stage / name)) as destination:
                source.backup(destination)
            progress("读取导出快照", completed, 2)
        stats = ExportStats()
        manifest = export_public(
            stage / "index.sqlite3", stage / "annotations.sqlite3", output / "public-data",
            progress=progress, stats=stats,
            status=lambda message: cache_report(stats.reused_photos, stats.reused_photos + stats.generated_photos, "张照片"),
        )
        pack_public_data(output / "public-data", output / ARTIFACTS[0], progress=progress)
    return {
        "message": f"公开数据包已生成：{manifest['summary']['featuredPhotos']} 张精选，复用 {stats.reused_photos} 张，新增 {stats.generated_photos} 张",
        "artifacts": list(ARTIFACTS), "counters": {"reused": stats.reused_photos, "generated": stats.generated_photos},
    }
