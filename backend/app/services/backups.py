from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from app.core.config import Settings
from app.core.database import Database, build_database_url
from app.services.operations import schema_versions

BACKUP_NAME = re.compile(
    r"^budget-(?P<stamp>\d{8}T\d{6}Z)-(?P<schema>[A-Za-z0-9_-]+)\.(?P<kind>sql|sqlite3)\.gz$"
)
SAFE_DB_NAME = re.compile(r"^[A-Za-z0-9_]+$")


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BackupArtifact:
    archive: Path
    manifest: Path
    sha256: str
    size: int
    schema_version: str
    database_type: str


def _now() -> datetime:
    return datetime.now(UTC)


def _backup_dir(settings: Settings) -> Path:
    path = settings.backup_dir.expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _schema_version(settings: Settings) -> str:
    database = Database.from_settings(settings)
    try:
        with database.session_factory() as db:
            current, head = schema_versions(db)
            return current or head
    finally:
        database.engine.dispose()


def _manifest_path(archive: Path) -> Path:
    return archive.with_name(f"{archive.name}.json")


def _write_manifest(artifact: BackupArtifact, created_at: datetime) -> None:
    payload = {
        "format": 1,
        "created_at": created_at.isoformat(),
        "database_type": artifact.database_type,
        "schema_version": artifact.schema_version,
        "archive": artifact.archive.name,
        "sha256": artifact.sha256,
        "size": artifact.size,
    }
    tmp = artifact.manifest.with_suffix(artifact.manifest.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, artifact.manifest)
    try:
        os.chmod(artifact.manifest, 0o600)
    except OSError:
        pass


def _sqlite_backup(settings: Settings, archive: Path) -> None:
    source = Path(build_database_url(settings).database or "").expanduser().resolve()
    if not source.exists():
        raise BackupError("sqlite_source_missing")
    with tempfile.TemporaryDirectory(prefix="budget-backup-") as temporary:
        snapshot = Path(temporary) / "snapshot.sqlite3"
        source_db = sqlite3.connect(source)
        target_db = sqlite3.connect(snapshot)
        try:
            source_db.backup(target_db)
        finally:
            target_db.close()
            source_db.close()
        with snapshot.open("rb") as raw, gzip.open(archive, "wb", compresslevel=6) as compressed:
            shutil.copyfileobj(raw, compressed, length=1024 * 1024)


def _option_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")


def _mysql_option_file(settings: Settings, directory: Path) -> Path:
    if settings.db_password is None or settings.db_host is None or settings.db_user is None:
        raise BackupError("mysql_configuration_incomplete")
    option_file = directory / "mysql-client.cnf"
    lines = [
        "[client]",
        f'host="{_option_escape(settings.db_host)}"',
        f"port={settings.db_port or 3306}",
        f'user="{_option_escape(settings.db_user)}"',
        f'password="{_option_escape(settings.db_password.get_secret_value())}"',
        "default-character-set=utf8mb4",
    ]
    if settings.db_ssl_required:
        lines.append(f"ssl-mode={settings.db_ssl_mode}")
        if settings.db_ssl_ca is not None:
            lines.append(f'ssl-ca="{_option_escape(str(settings.db_ssl_ca.expanduser()))}"')
    option_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(option_file, 0o600)
    return option_file


def _mysql_dump(settings: Settings, archive: Path) -> None:
    if not settings.db_name:
        raise BackupError("mysql_database_missing")
    with tempfile.TemporaryDirectory(prefix="budget-mysql-") as temporary:
        options = _mysql_option_file(settings, Path(temporary))
        command = [
            settings.mysqldump_path,
            f"--defaults-extra-file={options}",
            "--single-transaction",
            "--set-gtid-purged=OFF",
            "--quick",
            "--skip-lock-tables",
            "--no-tablespaces",
            "--triggers",
            "--hex-blob",
            "--default-character-set=utf8mb4",
            settings.db_name,
        ]
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except FileNotFoundError as exc:
            raise BackupError("mysqldump_not_found") from exc
        assert process.stdout is not None
        with gzip.open(archive, "wb", compresslevel=6) as compressed:
            for block in iter(lambda: process.stdout.read(1024 * 1024), b""):
                compressed.write(block)
        process.wait()
        if process.returncode != 0:
            archive.unlink(missing_ok=True)
            raise BackupError(f"mysqldump_failed_{process.returncode}")
        if archive.stat().st_size < 128:
            archive.unlink(missing_ok=True)
            raise BackupError("mysqldump_empty")


def _parse_created(path: Path) -> datetime | None:
    match = BACKUP_NAME.match(path.name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group("stamp"), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def apply_retention(settings: Settings) -> dict[str, int]:
    directory = _backup_dir(settings)
    archives = sorted(
        ((created, path) for path in directory.iterdir() if (created := _parse_created(path))),
        reverse=True,
    )
    if not archives:
        return {"kept": 0, "deleted": 0}
    now = _now()
    keep: set[Path] = {archives[0][1]}
    daily: set[tuple[int, int]] = set()
    weekly: set[tuple[int, int]] = set()
    monthly: set[tuple[int, int]] = set()
    for created, path in archives:
        age_days = (now.date() - created.date()).days
        day_key = (created.year, created.timetuple().tm_yday)
        iso = created.isocalendar()
        week_key = (iso.year, iso.week)
        month_key = (created.year, created.month)
        if age_days < settings.backup_retention_daily and day_key not in daily:
            daily.add(day_key)
            keep.add(path)
        if len(weekly) < settings.backup_retention_weekly and week_key not in weekly:
            weekly.add(week_key)
            keep.add(path)
        if len(monthly) < settings.backup_retention_monthly and month_key not in monthly:
            monthly.add(month_key)
            keep.add(path)
    deleted = 0
    for _, path in archives:
        if path in keep:
            continue
        _manifest_path(path).unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        deleted += 1
    return {"kept": len(keep), "deleted": deleted}


def create_backup(settings: Settings) -> dict[str, object]:
    directory = _backup_dir(settings)
    created_at = _now()
    schema = _schema_version(settings)
    is_sqlite = build_database_url(settings).get_backend_name() == "sqlite"
    kind = "sqlite3" if is_sqlite else "sql"
    archive = directory / f"budget-{created_at.strftime('%Y%m%dT%H%M%SZ')}-{schema}.{kind}.gz"
    partial = archive.with_suffix(archive.suffix + ".partial")
    try:
        if is_sqlite:
            _sqlite_backup(settings, partial)
        else:
            _mysql_dump(settings, partial)
        os.replace(partial, archive)
        os.chmod(archive, 0o600)
    finally:
        partial.unlink(missing_ok=True)
    artifact = BackupArtifact(
        archive=archive,
        manifest=_manifest_path(archive),
        sha256=_sha256(archive),
        size=archive.stat().st_size,
        schema_version=schema,
        database_type="sqlite" if is_sqlite else "mysql",
    )
    _write_manifest(artifact, created_at)
    retention = apply_retention(settings)
    return {
        "archive": artifact.archive.name,
        "sha256": artifact.sha256,
        "size": artifact.size,
        "schema_version": artifact.schema_version,
        "database_type": artifact.database_type,
        "retention_deleted": retention["deleted"],
    }


def latest_backup(settings: Settings) -> Path:
    directory = _backup_dir(settings)
    archives = [(created, path) for path in directory.iterdir() if (created := _parse_created(path))]
    if not archives:
        raise BackupError("backup_not_found")
    return max(archives, key=lambda item: item[0])[1]


def verify_backup(settings: Settings, archive: Path | None = None) -> dict[str, object]:
    selected = (archive or latest_backup(settings)).expanduser().resolve()
    if not selected.is_file() or selected.parent != _backup_dir(settings):
        raise BackupError("backup_path_invalid")
    manifest_path = _manifest_path(selected)
    if not manifest_path.exists():
        raise BackupError("backup_manifest_missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError("backup_manifest_invalid") from exc
    digest = _sha256(selected)
    if digest != manifest.get("sha256"):
        raise BackupError("backup_checksum_mismatch")
    if selected.stat().st_size != manifest.get("size"):
        raise BackupError("backup_size_mismatch")

    database_type = manifest.get("database_type")
    if database_type == "sqlite":
        with tempfile.TemporaryDirectory(prefix="budget-verify-") as temporary:
            restored = Path(temporary) / "restore.sqlite3"
            with gzip.open(selected, "rb") as compressed, restored.open("wb") as raw:
                shutil.copyfileobj(compressed, raw, length=1024 * 1024)
            connection = sqlite3.connect(restored)
            try:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()
                if not integrity or integrity[0] != "ok":
                    raise BackupError("sqlite_integrity_failed")
                row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
                restored_schema = row[0] if row else None
            finally:
                connection.close()
            if restored_schema != manifest.get("schema_version"):
                raise BackupError("backup_schema_mismatch")
            verification = "full_sqlite_restore"
    elif database_type == "mysql":
        header = bytearray()
        create_table_found = False
        try:
            with gzip.open(selected, "rb") as compressed:
                while True:
                    block = compressed.read(1024 * 1024)
                    if not block:
                        break
                    if len(header) < 4 * 1024 * 1024:
                        header.extend(block[: 4 * 1024 * 1024 - len(header)])
                    if b"CREATE TABLE" in block:
                        create_table_found = True
        except (OSError, EOFError) as exc:
            raise BackupError("backup_gzip_invalid") from exc
        if b"MySQL dump" not in bytes(header) or not create_table_found:
            raise BackupError("mysql_dump_structure_invalid")
        verification = "checksum_gzip_structure"
    else:
        raise BackupError("backup_type_invalid")

    return {
        "archive": selected.name,
        "sha256": digest,
        "size": selected.stat().st_size,
        "schema_version": manifest.get("schema_version"),
        "database_type": database_type,
        "verification": verification,
    }


def _run_mysql(
    settings: Settings, args: list[str], *, stdin: BinaryIO | None = None
) -> subprocess.CompletedProcess[bytes]:
    with tempfile.TemporaryDirectory(prefix="budget-restore-") as temporary:
        options = _mysql_option_file(settings, Path(temporary))
        command = [settings.mysql_path, f"--defaults-extra-file={options}", *args]
        try:
            return subprocess.run(
                command,
                stdin=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except FileNotFoundError as exc:
            raise BackupError("mysql_client_not_found") from exc


def restore_test_backup(settings: Settings, target_db_name: str | None = None) -> dict[str, object]:
    archive = latest_backup(settings)
    verified = verify_backup(settings, archive)
    if verified["database_type"] == "sqlite":
        # verify_backup performs a complete restore to a disposable SQLite file and
        # runs integrity/schema checks, so it is already a full local restore drill.
        return {**verified, "restore_test": "passed", "target": "temporary_sqlite"}

    if not target_db_name or not SAFE_DB_NAME.fullmatch(target_db_name):
        raise BackupError("restore_target_required")
    if target_db_name == settings.db_name:
        raise BackupError("restore_target_is_production")
    if not target_db_name.startswith("budget_restore_"):
        raise BackupError("restore_target_name_guard")

    count_query = (
        "SELECT COUNT(*) FROM information_schema.tables "
        f"WHERE table_schema='{target_db_name}';"
    )
    probe = _run_mysql(settings, ["--batch", "--skip-column-names", "-e", count_query])
    if probe.returncode != 0:
        raise BackupError("restore_target_unavailable")
    try:
        table_count = int(probe.stdout.decode("utf-8").strip() or "0")
    except ValueError as exc:
        raise BackupError("restore_target_probe_invalid") from exc
    if table_count != 0:
        raise BackupError("restore_target_not_empty")

    with gzip.open(archive, "rb") as dump:
        restored = _run_mysql(settings, [target_db_name], stdin=dump)
    if restored.returncode != 0:
        raise BackupError("restore_import_failed")
    version_query = "SELECT version_num FROM alembic_version LIMIT 1;"
    version = _run_mysql(
        settings,
        ["--batch", "--skip-column-names", target_db_name, "-e", version_query],
    )
    if version.returncode != 0:
        raise BackupError("restore_schema_probe_failed")
    restored_schema = version.stdout.decode("utf-8").strip()
    if restored_schema != verified["schema_version"]:
        raise BackupError("restore_schema_mismatch")
    return {
        **verified,
        "restore_test": "passed",
        "target": target_db_name,
    }
