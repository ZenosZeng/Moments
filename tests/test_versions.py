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
    assert f"**{version}**" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"## {version} - " in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
