from __future__ import annotations

import json
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def app_version() -> str:
    return tomllib.loads((ROOT / "pixi.toml").read_text(encoding="utf-8"))["workspace"]["version"]


def test_package_versions_match_pixi_workspace():
    for path in ("package.json", "apps/local-ui/package.json", "apps/public-ui/package.json"):
        assert read_json(path)["version"] == app_version(), path


def test_lockfile_versions_match_package_manifests():
    for prefix in ("", "apps/public-ui/"):
        lock = read_json(f"{prefix}package-lock.json")
        version = read_json(f"{prefix}package.json")["version"]
        assert lock["version"] == lock["packages"][""]["version"] == version
    assert read_json("package-lock.json")["packages"]["apps/local-ui"]["version"] == app_version()


def test_current_version_is_documented():
    version = app_version()
    feature = ".".join(version.split(".")[:2]) + ".0"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    history = (ROOT / "docs/changelog.md").read_text(encoding="utf-8")
    assert f"最新版本：**v{version}**" in readme
    assert f"当前功能版本：**v{feature}**" in readme
    assert f"**v{feature} 主要功能**" in readme
    assert f"## v{version} · " in history
    assert f"## v{feature} · " in history
    assert "docs/changelog.md" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_pr_workflow_is_documented_for_agents_and_contributors():
    for path in ("AGENTS.md", "CLAUDE.md", "docs/development.md", ".github/PULL_REQUEST_TEMPLATE.md"):
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "main" in text, path
        assert "PR" in text, path


def test_display_name_matches_in_all_entry_points():
    for path in (
        "README.md",
        "AGENTS.md",
        "apps/local-ui/index.html",
        "apps/public-ui/index.html",
        "apps/local-ui/src/App.vue",
        "apps/local-ui/src/TrailsPreview.vue",
        "apps/public-ui/src/App.vue",
        "src/pic_timeline/templates/index.html",
    ):
        assert "Moments · 拾光集" in (ROOT / path).read_text(encoding="utf-8"), path
    assert "拾光集" in (ROOT / "user_guide.md").read_text(encoding="utf-8")
    case_path = "docs/Moments_拾光集_功能案例.pdf"
    assert case_path in (ROOT / "README.md").read_text(encoding="utf-8")
    assert case_path in (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert f"!/{case_path}" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert (ROOT / case_path).is_file()
    assert read_json("package.json")["name"] == "moments"
