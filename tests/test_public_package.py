import hashlib
from pathlib import Path
import stat
import zipfile

import pytest

from pic_timeline.public_package import extract_public_data, pack_public_data


PHOTO = "0123456789abcdef0123.webp"


def public_source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    (source / "data").mkdir(parents=True)
    (source / "media").mkdir()
    (source / "data" / "trips.json").write_text('{"trips": []}', encoding="utf-8")
    (source / "media" / PHOTO).write_bytes(b"synthetic image")
    return source


def test_roundtrip_excludes_cache_and_private_root_files(tmp_path):
    source = public_source(tmp_path)
    (source / ".media-cache-version").write_text("1", encoding="ascii")
    (source / "annotations.sqlite3").write_bytes(b"private")
    archive = tmp_path / "public-data.zip"
    checksum = pack_public_data(source, archive)
    assert checksum.read_text().split()[0] == hashlib.sha256(archive.read_bytes()).hexdigest()
    with zipfile.ZipFile(archive) as package:
        assert package.namelist() == ["data/trips.json", f"media/{PHOTO}"]
        assert package.getinfo(f"media/{PHOTO}").compress_type == zipfile.ZIP_STORED
    output = tmp_path / "extracted"
    extract_public_data(archive, output, checksum)
    assert (output / "media" / PHOTO).read_bytes() == b"synthetic image"
    assert sorted(path.name for path in output.iterdir()) == ["data", "media"]


@pytest.mark.parametrize("name", ["data/private.json", "media/private.jpg", "media/private.webp"])
def test_pack_rejects_non_whitelisted_files(tmp_path, name):
    source = public_source(tmp_path)
    (source / name).write_bytes(b"private")
    with pytest.raises(ValueError, match="白名单|只能包含"):
        pack_public_data(source, tmp_path / "public-data.zip")


@pytest.mark.parametrize("name", [
    "../outside.txt", "/outside.txt", "C:/outside.txt", "data/../../outside.txt",
    "media\\outside.webp", "data/annotations.sqlite3", ".media-cache-version",
])
def test_extract_rejects_unsafe_or_private_paths_before_writing(tmp_path, name):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("data/trips.json", '{"trips": []}')
        package.writestr(name, "private")
    output = tmp_path / "extracted"
    with pytest.raises(ValueError, match="白名单"):
        extract_public_data(archive, output)
    assert not output.exists()
    assert not (tmp_path / "outside.txt").exists()


def test_extract_rejects_zip_symlinks(tmp_path):
    archive = tmp_path / "unsafe.zip"
    entry = zipfile.ZipInfo(f"media/{PHOTO}")
    entry.create_system = 3
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("data/trips.json", '{"trips": []}')
        package.writestr(entry, "../../private")
    with pytest.raises(ValueError, match="链接"):
        extract_public_data(archive, tmp_path / "extracted")


def test_extract_rejects_duplicate_entries(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("data/trips.json", '{"trips": []}')
        with pytest.warns(UserWarning, match="Duplicate"):
            package.writestr("data/trips.json", "{}")
    with pytest.raises(ValueError, match="重复"):
        extract_public_data(archive, tmp_path / "extracted")


def test_extract_requires_matching_checksum_and_new_directory(tmp_path):
    source = public_source(tmp_path)
    archive = tmp_path / "public-data.zip"
    checksum = pack_public_data(source, archive)
    output = tmp_path / "extracted"
    checksum.write_text("0" * 64 + "  public-data.zip\n", encoding="ascii")
    with pytest.raises(ValueError, match="校验失败"):
        extract_public_data(archive, output, checksum)
    assert not output.exists()
    output.mkdir()
    with pytest.raises(ValueError, match="覆盖"):
        extract_public_data(archive, output)


def test_empty_media_directory_is_recreated(tmp_path):
    source = public_source(tmp_path)
    (source / "media" / PHOTO).unlink()
    archive = tmp_path / "public-data.zip"
    checksum = pack_public_data(source, archive)
    output = tmp_path / "extracted"
    extract_public_data(archive, output, checksum)
    assert (output / "media").is_dir()
