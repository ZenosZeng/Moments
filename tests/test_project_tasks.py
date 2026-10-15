import importlib.util
import json
import sqlite3
from pathlib import Path
import zipfile

import yaml


spec = importlib.util.spec_from_file_location(
    "project_tasks", Path(__file__).resolve().parents[1] / "scripts" / "project_tasks.py"
)
tasks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tasks)


def test_public_frontend_is_inside_main_repository():
    assert tasks.PUBLIC_ROOT == tasks.STUDIO_ROOT / "apps" / "public-ui"
    assert (tasks.PUBLIC_ROOT / "package.json").is_file()


def test_release_only_packages_local_output(tmp_path, monkeypatch):
    root = tmp_path / "Moments"
    public_root = root / "apps" / "public-ui"
    (public_root / "dist").mkdir(parents=True)
    (public_root / "dist" / "index.html").write_text("<h1>Demo</h1>", encoding="utf-8")
    source = tmp_path / "photos"
    source.mkdir()
    (root / "config").mkdir()
    (root / "config" / "local.yaml").write_text(
        yaml.safe_dump({
            "photos": {"sources": [{"id": "archive", "path": source.as_posix()}]},
            "publish": {"base_path": "/example/"},
        }), encoding="utf-8"
    )
    (root / "data" / "db").mkdir(parents=True)
    with sqlite3.connect(root / "data" / "db" / "photo_index.sqlite3") as connection:
        connection.executescript("CREATE TABLE photos(relative_path TEXT); CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);")
    (root / "data" / "db" / "annotations.sqlite3").touch()
    data = root / "data" / "exports" / "public-data" / "data"
    data.mkdir(parents=True)
    (root / "data" / "exports" / "public-data" / "media").mkdir()
    (data / "trips.json").write_text(json.dumps({"trips": []}), encoding="utf-8")
    (root / "data" / "exports" / "public-data" / ".media-cache-version").write_text("1", encoding="utf-8")
    monkeypatch.chdir(root)
    monkeypatch.setattr(tasks, "STUDIO_ROOT", root)
    monkeypatch.setattr(tasks, "PUBLIC_ROOT", public_root)
    monkeypatch.setattr(tasks, "_require_public_repo", lambda: None)
    monkeypatch.setattr(tasks, "_ensure_node_modules", lambda *a, **kw: None)
    commands = []
    monkeypatch.setattr(tasks, "_run", lambda command, **kw: commands.append(command))
    monkeypatch.setattr(tasks, "_run_public", lambda *command: commands.append(list(command)))
    tasks.release_local([])
    assert ["npm", "run", "build", "--", "--base", "/example/"] in commands
    assert ["npm", "run", "import-data", "--", str(root / "data" / "exports" / "public-data")] in commands
    assert not any(command[0] in {"git", "gh"} for command in commands)
    with zipfile.ZipFile(root / "data" / "exports" / "site.zip") as archive:
        assert archive.namelist() == ["index.html"]
    with zipfile.ZipFile(root / "data" / "exports" / "public-data.zip") as archive:
        assert archive.namelist() == ["data/trips.json"]
    assert (root / "data" / "exports" / "public-data.zip.sha256").is_file()


def test_app_uses_private_config_without_launch_arguments(tmp_path, monkeypatch):
    source = tmp_path / "photos"
    source.mkdir()
    root = tmp_path / "Moments"
    (root / "config").mkdir(parents=True)
    (root / "config" / "local.yaml").write_text(
        yaml.safe_dump({"photos": {"sources": [{"id": "archive", "path": source.as_posix()}]}}), encoding="utf-8"
    )
    monkeypatch.setattr(tasks, "STUDIO_ROOT", root)
    monkeypatch.setattr(tasks, "_ensure_node_modules", lambda *a, **kw: None)
    monkeypatch.setattr(tasks, "_studio_frontend_is_stale", lambda: False)
    commands = []
    monkeypatch.setattr(tasks, "_run", lambda command, **kw: commands.append(command))
    tasks.run_app([])
    assert commands == [[tasks.sys.executable, "-m", "pic_timeline.web", "--config", str(root / "config" / "local.yaml")]]


def test_demo_preparation_preserves_existing_data(tmp_path, monkeypatch):
    demo = tmp_path / "demo" / "data"
    target = tmp_path / "public" / "data"
    demo.mkdir(parents=True)
    target.mkdir(parents=True)
    (demo / "trips.json").write_text("demo", encoding="utf-8")
    (target / "trips.json").write_text("existing", encoding="utf-8")
    monkeypatch.setattr(tasks, "PUBLIC_ROOT", tmp_path)
    tasks._prepare_demo()
    assert (target / "trips.json").read_text(encoding="utf-8") == "existing"
