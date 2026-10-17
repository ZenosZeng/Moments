from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from pic_timeline.analysis import scan_archive
from pic_timeline.compositions import FILTER_RECIPES, PRESETS, apply_filter, photo_id
from pic_timeline.web import create_app


@pytest.fixture
def workspace(tmp_path):
    source = tmp_path / "photos"
    month = source / "202405_a"
    month.mkdir(parents=True)
    for name, day, color in (("a", "02", "#387b68"), ("b", "02", "#9c6460"), ("c", "03", "#4775ac")):
        exif = Image.Exif()
        exif[36867] = f"2024:05:{day} 10:00:00"
        exif[270] = "private metadata must disappear"
        image = Image.new("RGB", (180, 120), color)
        image.paste("#d9c786", (40, 40, 100, 100))
        image.save(month / f"{name}.jpg", exif=exif)
    index = tmp_path / "data" / "db" / "index.sqlite3"
    scan_archive(source, index, refresh=True)
    app = create_app(index_path=index, annotation_path=tmp_path / "data/db/annotations.sqlite3",
                     thumbnail_root=tmp_path / "data/cache/thumbnails", source_finder=lambda: source,
                     composition_root=tmp_path / "data/compositions")
    app.config.update(TESTING=True)
    client = app.test_client()
    for day, city, place, names in (("02", "深圳", "海边", ["a"]), ("03", "上海", "外滩、街巷", ["c"])):
        result = client.put(f"/api/days/2024-05-{day}/annotation", json={
            "places": [{"city": city, "name": place}], "isPublic": False,
            "featuredPhotos": [{"relativePath": f"202405_a/{name}.jpg"} for name in names]
        })
        assert result.status_code == 200
    return app, client, source, tmp_path / "data/compositions"


def payload():
    return {"title": "街巷小记", "location": "海边，街巷", "captionTitle": "", "caption": "",
            "sourceDates": ["2024-05-03", "2024-05-02"], "photos": [
                {"id": photo_id("2024-05-03", "202405_a/c.jpg"), "captureDate": "2024-05-03", "relativePath": "202405_a/c.jpg", "preset": "warm-film", "strength": 65},
                {"id": photo_id("2024-05-02", "202405_a/a.jpg"), "captureDate": "2024-05-02", "relativePath": "202405_a/a.jpg", "preset": "original", "strength": 100},
            ]}


def update_payload(group):
    return {**payload(), "etag": group["etag"]}


def test_sources_only_featured_including_private_dates(workspace):
    _, client, _, _ = workspace
    catalog = client.get("/api/compositions/sources").get_json()
    assert len(catalog["dates"]) == 2
    assert len(catalog["presets"]) == 9
    assert [preset["id"] for preset in catalog["presets"]] == [
        "original", "clear", "warm-film", "cool-city", "soft-fade", "vivid", "mono", "forest", "cinema",
    ]
    assert catalog["presetNames"]["sunset"] == "落日暖金"
    day = client.get("/api/compositions/sources/2024-05-02").get_json()
    assert [photo["relativePath"] for photo in day["photos"]] == ["202405_a/a.jpg"]
    assert day["places"] == ["海边"]
    assert client.get("/api/compositions/source-image?date=2024-05-02&path=202405_a/b.jpg").status_code == 400


def test_save_multi_date_metadata_order_files_and_optional_copy(workspace):
    app, client, source, root = workspace
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source.rglob("*.jpg")}
    response = client.post("/api/compositions", json=payload())
    assert response.status_code == 201, response.get_json()
    group = response.get_json()
    assert group["cities"] == ["深圳", "上海"]
    assert group["time"] == {"start": "2024-05-02", "end": "2024-05-03", "dates": ["2024-05-02", "2024-05-03"]}
    assert group["sourceDates"] == ["2024-05-02", "2024-05-03"]
    assert group["caption"] == group["captionTitle"] == ""
    folder = Path(group["directory"])
    manifest = json.loads((folder / "group.json").read_text(encoding="utf-8"))
    assert "etag" not in manifest and "src" not in manifest["photos"][0]
    assert "directory" not in manifest
    assert len(group["id"]) == 32 and all(char in "0123456789abcdef" for char in group["id"])
    assert folder.parent == root.resolve()
    assert folder.name == "2024-05-02至2024-05-03_深圳、上海_街巷小记"
    assert (folder / "文案.txt").read_text(encoding="utf-8") == "街巷小记\n\n\n"
    schema = json.loads(Path("docs/composition-v1.schema.json").read_text(encoding="utf-8"))
    definitions = schema["properties"]["photos"]["items"]["properties"]
    for photo in manifest["photos"]:
        for key in ("file", "baseFile"):
            assert re.fullmatch(definitions[key]["pattern"], photo[key])
            with Image.open(folder / photo[key]) as image:
                assert not image.getexif()
                assert "xmp" not in image.info and "comment" not in image.info
    assert [photo["captureDate"] for photo in manifest["photos"]] == ["2024-05-03", "2024-05-02"]
    assert before == {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source.rglob("*.jpg")}
    assert not app.extensions["annotation_store"].get("2024-05-02")["isPublic"]
    assert len(client.get("/api/compositions").get_json()["groups"]) == 1
    photo_response = client.get(group["photos"][0]["src"])
    assert photo_response.status_code == 200 and photo_response.mimetype == "image/jpeg"


def test_directory_is_stable_after_rename_and_returned_on_every_read(workspace):
    _, client, _, root = workspace
    group = client.post("/api/compositions", json=payload()).get_json()
    directory = group["directory"]
    changed = client.put(f"/api/compositions/{group['id']}", json={**update_payload(group), "title": "改名后的图文"})
    assert changed.status_code == 200
    assert changed.get_json()["directory"] == directory
    assert client.get(f"/api/compositions/{group['id']}").get_json()["directory"] == directory
    assert client.get("/api/compositions").get_json()["groups"][0]["directory"] == directory
    assert (Path(directory) / "group.json").is_file()


def test_readable_names_handle_collisions_invalid_characters_and_order(workspace):
    _, client, _, root = workspace
    body = {**payload(), "title": '街巷: <>"/\\|?* 小记. ', "captionTitle": "分享标题", "caption": "可以直接复制的正文"}
    first = client.post("/api/compositions", json=body).get_json()
    second = client.post("/api/compositions", json=body).get_json()
    folder = Path(first["directory"])
    assert folder.parent == root.resolve()
    assert not any(character in folder.name for character in '<>:"/\\|?*')
    assert not folder.name.endswith((".", " "))
    assert Path(second["directory"]).name == f"{folder.name}_2"
    assert (folder / "文案.txt").read_text(encoding="utf-8") == "分享标题\n\n可以直接复制的正文\n"
    assert [Path(photo["file"]).name for photo in first["photos"]] == ["0001_2024-05-03_v0001.jpg", "0002_2024-05-02_v0001.jpg"]
    body.update(etag=first["etag"], photos=list(reversed(body["photos"])))
    changed = client.put(f"/api/compositions/{first['id']}", json=body).get_json()
    assert changed["directory"] == first["directory"]
    assert [Path(photo["file"]).name for photo in changed["photos"]] == ["0001_2024-05-02_v0002.jpg", "0002_2024-05-03_v0002.jpg"]
    assert {path.name for path in (folder / "images").iterdir()} == {Path(photo["file"]).name for photo in changed["photos"]}
    assert len(client.get("/api/compositions").get_json()["groups"]) == 2


def test_legacy_hash_folders_and_assets_migrate_only_when_saved(workspace, monkeypatch):
    app, client, _, root = workspace
    group = client.post("/api/compositions", json=payload()).get_json()
    folder = Path(group["directory"])
    manifest = json.loads((folder / "group.json").read_text(encoding="utf-8"))
    content = {}
    for photo in manifest["photos"]:
        for field, kind in (("baseFile", "base"), ("file", "images")):
            path = folder / photo[field]
            content[photo["id"], field] = path.read_bytes()
            legacy = f"{kind}/{photo['id']}-{'0' * 20}.jpg"
            path.rename(folder / legacy)
            photo[field] = legacy
    (folder / "group.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    folder.rename(root / group["id"])
    old_folder = root / group["id"]
    app.extensions["composition_store"]._folders = {}
    legacy = client.get(f"/api/compositions/{group['id']}").get_json()
    assert legacy["directory"] == old_folder.as_posix()
    assert client.get(legacy["photos"][0]["src"]).status_code == 200
    assert old_folder.is_dir()
    old_manifest = (old_folder / "group.json").read_bytes()
    rename = Path.rename
    def busy_directory(path, target):
        if path == old_folder:
            raise PermissionError("simulated image viewer lock")
        return rename(path, target)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", busy_directory)
        failed = client.put(f"/api/compositions/{group['id']}", json=update_payload(legacy))
        assert failed.status_code == 400
        assert "本次未保存" in failed.get_json()["error"]
        assert (old_folder / "group.json").read_bytes() == old_manifest
    response = client.put(f"/api/compositions/{group['id']}", json=update_payload(legacy))
    assert response.status_code == 200, response.get_json()
    changed = response.get_json()
    assert changed["id"] == group["id"]
    assert Path(changed["directory"]).name == folder.name
    assert not old_folder.exists()
    for photo in changed["photos"]:
        for field in ("baseFile", "file"):
            assert photo["id"] not in photo[field]
            assert (Path(changed["directory"]) / photo[field]).read_bytes() == content[photo["id"], field]
    assert client.get("/api/compositions").get_json()["groups"][0]["directory"] == changed["directory"]


def test_missing_finished_image_is_rebuilt_from_baseline(workspace):
    _, client, _, _ = workspace
    group = client.post("/api/compositions", json=payload()).get_json()
    (Path(group["directory"]) / group["photos"][0]["file"]).unlink()
    response = client.put(f"/api/compositions/{group['id']}", json=update_payload(group))
    assert response.status_code == 200, response.get_json()
    saved = response.get_json()
    assert (Path(saved["directory"]) / saved["photos"][0]["file"]).is_file()


@pytest.mark.parametrize("preset", [item["id"] for item in FILTER_RECIPES if item not in PRESETS])
def test_retired_presets_still_render_and_survive_edit(workspace, preset):
    _, client, _, root = workspace
    body = payload()
    body["photos"][0]["preset"] = preset
    group = client.post("/api/compositions", json=body).get_json()
    image_file = Path(group["directory"]) / group["photos"][0]["file"]
    before = image_file.read_bytes()
    assert client.get(group["photos"][0]["src"]).status_code == 200
    body.update(etag=group["etag"], title="保留旧版滤镜")
    response = client.put(f"/api/compositions/{group['id']}", json=body)
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["photos"][0]["filter"]["preset"] == preset
    saved = response.get_json()
    assert (Path(saved["directory"]) / saved["photos"][0]["file"]).read_bytes() == before


def test_single_date_and_display_date_are_derived_not_supplied(workspace):
    _, client, _, _ = workspace
    assert client.patch("/api/records/2024-05-02", json={"displayDate": "2024-05-01"}).status_code == 200
    body = payload()
    body["sourceDates"] = ["2024-05-02"]
    body["photos"] = body["photos"][1:]
    group = client.post("/api/compositions", json=body).get_json()
    assert group["cities"] == ["深圳"]
    assert group["time"]["start"] == group["time"]["end"] == "2024-05-01"


def test_manual_time_city_are_saved_reloaded_and_can_return_to_automatic(workspace):
    _, client, _, root = workspace
    body = {**payload(), "autoFill": {"time": False, "cities": False},
            "time": {"start": "2024-06-01", "end": "2024-06-03"}, "cities": ["杭州", "南京", "杭州"]}
    response = client.post("/api/compositions", json=body)
    assert response.status_code == 201, response.get_json()
    group = response.get_json()
    assert group["autoFill"] == {"time": False, "cities": False}
    assert group["time"] == {"start": "2024-06-01", "end": "2024-06-03", "dates": ["2024-06-01", "2024-06-03"]}
    assert group["cities"] == ["杭州", "南京"]
    assert group["days"][0]["cities"] == ["深圳"]
    assert client.get(f"/api/compositions/{group['id']}").get_json()["cities"] == ["杭州", "南京"]
    # Old callers that omit override fields retain the existing manual metadata.
    edited = client.put(f"/api/compositions/{group['id']}", json=update_payload(group))
    assert edited.status_code == 200, edited.get_json()
    assert edited.get_json()["cities"] == ["杭州", "南京"]
    automatic = client.put(f"/api/compositions/{group['id']}", json={**update_payload(edited.get_json()), "autoFill": {"time": True, "cities": True}})
    assert automatic.status_code == 200
    assert automatic.get_json()["time"]["start"] == "2024-05-02"
    assert automatic.get_json()["cities"] == ["深圳", "上海"]
    saved = json.loads((Path(group["directory"]) / "group.json").read_text(encoding="utf-8"))
    assert saved["autoFill"] == {"time": True, "cities": True}


@pytest.mark.parametrize("changes", [
    {"autoFill": {"time": "yes", "cities": True}}, {"autoFill": {"time": False}},
    {"autoFill": {"time": False, "cities": True}, "time": {"start": "2024-05-10", "end": "2024-05-01"}},
    {"autoFill": {"time": False, "cities": True}, "time": {"start": "bad", "end": "2024-05-01"}},
    {"autoFill": {"time": True, "cities": False}, "cities": "上海"},
    {"autoFill": {"time": True, "cities": False}, "cities": [None]},
])
def test_invalid_metadata_overrides_are_rejected(workspace, changes):
    _, client, _, _ = workspace
    assert client.post("/api/compositions", json={**payload(), **changes}).status_code == 400


def test_legacy_manifest_without_auto_fill_still_loads_as_automatic(workspace):
    _, client, _, root = workspace
    group = client.post("/api/compositions", json=payload()).get_json()
    path = Path(group["directory"]) / "group.json"
    legacy = json.loads(path.read_text(encoding="utf-8"))
    legacy.pop("autoFill")
    path.write_text(json.dumps(legacy), encoding="utf-8")
    loaded = client.get(f"/api/compositions/{group['id']}").get_json()
    saved = client.put(f"/api/compositions/{group['id']}", json=update_payload(loaded))
    assert saved.status_code == 200
    assert saved.get_json()["autoFill"] == {"time": True, "cities": True}


@pytest.mark.parametrize("changes", [
    {"title": " "}, {"location": ""}, {"caption": 123}, {"sourceDates": []}, {"photos": []},
    {"sourceDates": ["2024-99-02"]}, {"cities": ["伪造城市"]}, {"sourceDates": ["2024-05-04"]},
])
def test_validation_rejects_invalid_or_forged_inputs(workspace, changes):
    _, client, _, _ = workspace
    assert client.post("/api/compositions", json={**payload(), **changes}).status_code == 400
    assert client.get("/api/compositions").get_json()["groups"] == []


@pytest.mark.parametrize("field,value", [("relativePath", "../secret.jpg"), ("relativePath", "C:/photos/a.jpg"), ("id", "bad"), ("preset", "bad"), ("strength", True), ("strength", 101)])
def test_photo_validation(workspace, field, value):
    _, client, _, _ = workspace
    body = payload()
    body["photos"][0][field] = value
    assert client.post("/api/compositions", json=body).status_code == 400


def test_unfeatured_and_duplicate_photos_cannot_be_added(workspace):
    _, client, _, _ = workspace
    body = payload()
    body["photos"][1].update(id=photo_id("2024-05-02", "202405_a/b.jpg"), relativePath="202405_a/b.jpg")
    assert client.post("/api/compositions", json=body).status_code == 400
    body = payload()
    body["photos"].append(body["photos"][0])
    assert client.post("/api/compositions", json=body).status_code == 400


def test_edit_preserves_clean_baseline_and_handles_external_agent_updates(workspace):
    _, client, _, root = workspace
    group = client.post("/api/compositions", json=payload()).get_json()
    original_base = (Path(group["directory"]) / group["photos"][0]["baseFile"]).read_bytes()
    body = update_payload(group)
    body.update(captionTitle="手写标题", caption="手写正文")
    body["photos"][0].update(preset="mono", strength=100)
    response = client.put(f"/api/compositions/{group['id']}", json=body)
    assert response.status_code == 200
    changed = response.get_json()
    assert (Path(changed["directory"]) / changed["photos"][0]["baseFile"]).read_bytes() == original_base
    assert client.put(f"/api/compositions/{group['id']}", json=body).status_code == 409
    path = Path(group["directory"]) / "group.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(caption="Agent 写的正文")
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert client.get(f"/api/compositions/{group['id']}").get_json()["caption"] == "Agent 写的正文"
    assert "Agent 写的正文" in (path.parent / "文案.txt").read_text(encoding="utf-8")
    assert client.put(f"/api/compositions/{group['id']}", json=update_payload(changed)).status_code == 409


def test_saved_snapshots_survive_unfeature_and_source_removal(workspace):
    _, client, source, _ = workspace
    group = client.post("/api/compositions", json=payload()).get_json()
    assert client.put("/api/days/2024-05-03/featured", json={"photos": []}).status_code == 200
    (source / "202405_a/c.jpg").unlink()
    assert client.get(group["photos"][0]["src"]).status_code == 200
    assert client.put(f"/api/compositions/{group['id']}", json=update_payload(group)).status_code == 200


def test_agent_request_is_local_and_invalidated_by_save(workspace):
    _, client, _, root = workspace
    group = client.post("/api/compositions", json=payload()).get_json()
    response = client.post(f"/api/compositions/{group['id']}/agent-request", json={"etag": group["etag"]})
    assert response.status_code == 200
    assert response.get_json()["requestFile"] == "agent-request.md"
    path = Path(group["directory"]) / "agent-request.md"
    content = path.read_text(encoding="utf-8")
    assert "captionTitle" in content and "不上传" in content
    assert group["photos"][0]["file"] in content
    assert client.get(f"/api/compositions/{group['id']}").get_json()["caption"] == ""
    assert client.put(f"/api/compositions/{group['id']}", json=update_payload(group)).status_code == 200
    assert not path.exists()


def test_restart_loads_saved_group_without_original_source(workspace):
    app, client, _, root = workspace
    group = client.post("/api/compositions", json=payload()).get_json()
    restarted = create_app(index_path=app.extensions["photo_index"].path,
                           annotation_path=app.extensions["annotation_store"].path,
                           thumbnail_root=root.parent / "cache/thumbnails", composition_root=root)
    saved = restarted.test_client().get(f"/api/compositions/{group['id']}").get_json()
    assert saved["etag"] == group["etag"]
    assert saved["photos"][0]["filter"] == {"version": 1, "preset": "warm-film", "strength": 65}


def test_delete_uses_local_trash_and_does_not_touch_annotations(workspace):
    app, client, _, root = workspace
    group = client.post("/api/compositions", json=payload()).get_json()
    assert client.delete(f"/api/compositions/{group['id']}", json={"etag": "stale"}).status_code == 409
    assert client.delete(f"/api/compositions/{group['id']}", json={"etag": group["etag"]}).status_code == 200
    assert client.get(f"/api/compositions/{group['id']}").status_code == 404
    assert len(list((root / ".trash").glob("*/group.json"))) == 1
    assert app.extensions["annotation_store"].get("2024-05-02")["featuredPhotos"]
    assert client.get("/api/compositions/bad-id").status_code == 404


@pytest.mark.parametrize("preset", [item["id"] for item in FILTER_RECIPES])
def test_filter_strength_zero_identity_and_real_pixel_effect(preset):
    image = Image.new("RGB", (20, 20), (81, 122, 174))
    assert ImageChops.difference(image, apply_filter(image, preset, 0)).getbbox() is None
    changed = ImageChops.difference(image, apply_filter(image, preset, 100)).getbbox()
    assert (changed is None) == (preset == "original")


def test_failed_image_preparation_does_not_replace_saved_manifest(workspace, monkeypatch):
    import pic_timeline.compositions as module
    _, client, _, _ = workspace
    group = client.post("/api/compositions", json=payload()).get_json()
    def fail(*args, **kwargs):
        raise OSError("simulated write failure")
    monkeypatch.setattr(module, "_jpeg", fail)
    body = update_payload(group)
    body["photos"][0]["preset"] = "cool-city"
    with pytest.raises(OSError):
        client.put(f"/api/compositions/{group['id']}", json=body)
    unchanged = client.get(f"/api/compositions/{group['id']}").get_json()
    assert unchanged["etag"] == group["etag"]
