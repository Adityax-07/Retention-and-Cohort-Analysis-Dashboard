"""Verify the startup archive can be restored safely."""

import gzip
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from snapshot import restore_database


class SnapshotTests(unittest.TestCase):
    def test_restore_database(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = root / "original.db"
            with closing(sqlite3.connect(original)) as connection:
                connection.execute("CREATE TABLE transactions (id INTEGER)")
                connection.execute("CREATE TABLE orders (id INTEGER)")
                connection.execute("INSERT INTO transactions VALUES (1)")
                connection.commit()

            archive = root / "snapshot.gz"
            with original.open("rb") as source, gzip.open(archive, "wb") as target:
                target.write(source.read())

            restored = root / "data" / "retail.db"
            restore_database(archive, restored)
            with closing(sqlite3.connect(restored)) as connection:
                self.assertEqual(
                    connection.execute("SELECT id FROM transactions").fetchone()[0], 1
                )

    def test_missing_archive_leaves_no_database(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "data" / "retail.db"
            with self.assertRaises(FileNotFoundError):
                restore_database(Path(folder) / "missing.gz", destination)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
