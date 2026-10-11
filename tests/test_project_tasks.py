import importlib.util
import json
from pathlib import Path
import zipfile


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
    data = root / "exports" / "public-data" / "data"
    data.mkdir(parents=True)
    (data / "trips.json").write_text(json.dumps({"trips": []}), encoding="utf-8")
    monkeypatch.chdir(root)
    monkeypatch.setattr(tasks, "STUDIO_ROOT", root)
    monkeypatch.setattr(tasks, "PUBLIC_ROOT", public_root)
    monkeypatch.setattr(tasks, "_require_public_repo", lambda: None)
    monkeypatch.setattr(tasks, "_ensure_node_modules", lambda *a, **kw: None)
    commands = []
    monkeypatch.setattr(tasks, "_run", lambda command, **kw: commands.append(command))
    monkeypatch.setattr(tasks, "_run_public", lambda *command: commands.append(list(command)))
    tasks.release_local(["--base", "/example/"])
    assert ["npm", "run", "build", "--", "--base", "/example/"] in commands
    assert not any(command[0] in {"git", "gh"} for command in commands)
    with zipfile.ZipFile(root / "exports" / "site.zip") as archive:
        assert archive.namelist() == ["index.html"]
    with zipfile.ZipFile(root / "exports" / "public-data.zip") as archive:
        assert "data/trips.json" in archive.namelist()


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
