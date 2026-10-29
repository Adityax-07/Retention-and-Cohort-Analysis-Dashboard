"""Restore the checked-in dashboard database without downloading source data."""

import gzip
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from contextlib import closing


def restore_database(archive: str | Path, destination: str | Path) -> None:
    """Extract atomically and reject incomplete or invalid SQLite snapshots."""
    archive = Path(archive)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not archive.is_file():
        raise FileNotFoundError(f"Dashboard snapshot is missing: {archive}")

    fd, temporary_name = tempfile.mkstemp(
        prefix="retail-", suffix=".db", dir=destination.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with gzip.open(archive, "rb") as source, temporary.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        with closing(sqlite3.connect(temporary)) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise ValueError(f"SQLite integrity check failed: {result}")
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if not {"transactions", "orders"} <= tables:
                raise ValueError("Dashboard snapshot is missing required tables")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
