import importlib.util
import sqlite3
import zipfile
from pathlib import Path


spec = importlib.util.spec_from_file_location("legacy_migration", Path(__file__).resolve().parents[1] / "scripts" / "migrate_legacy_data.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def test_sqlite_backup_includes_committed_wal_and_keeps_source(tmp_path):
    source, target = tmp_path / "source.sqlite3", tmp_path / "target.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE notes(value TEXT)")
        connection.execute("INSERT INTO notes VALUES('kept')")
        connection.commit()
        migration.backup_database(source, target)
        assert connection.execute("SELECT value FROM notes").fetchone() == ("kept",)
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT value FROM notes").fetchone() == ("kept",)


def test_archive_preserves_hidden_git_and_data_but_excludes_dependencies(tmp_path, monkeypatch):
    root = tmp_path / "Moments"
    source = tmp_path / "legacy"
    (source / ".git").mkdir(parents=True)
    (source / ".git" / "config").write_text("local history", encoding="utf-8")
    (source / "data").mkdir()
    (source / "data" / "annotations.sqlite3").write_bytes(b"private snapshot")
    (source / "node_modules").mkdir()
    (source / "node_modules" / "reinstall.js").write_text("dependency", encoding="utf-8")
    monkeypatch.setattr(migration, "ROOT", root)
    result = migration.archive_repository(source, root / "_archive", "snapshot")
    with zipfile.ZipFile(root / "_archive" / result["file"]) as archive:
        assert archive.testzip() is None
        assert sorted(archive.namelist()) == ["legacy/.git/config", "legacy/data/annotations.sqlite3"]
    assert (source / "data" / "annotations.sqlite3").exists()
    assert (root / "_archive" / f'{result["file"]}.sha256').is_file()
