from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from hostdelta import cli
from hostdelta.model import stamp
from hostdelta.store import Store

NOW = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)


def sample_snapshot(at=NOW):
    return {"at": stamp(at), "host": "test-host", "domains": {
        "packages": {"status": "ok", "data": {"pkg": "1.0"}},
        "services": {"status": "ok", "data": {}},
        "files": {"status": "ok", "scope": ["/etc/example"], "data": {}}}}


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.tmp.name) / "state"
        self.store = Store(self.state_dir, create=True)
        self.snap_id = self.store.save(sample_snapshot(), "v1")
        self.store.ack("agent-a", stamp(NOW))
        self.event_id = self.store.record({"at": stamp(NOW), "summary": "test event"})
        with self.store.db:
            self.store.db.execute("INSERT INTO checkpoints(source, payload) VALUES (?, ?)", ("journalctl", json.dumps({"cursor": "c1"})))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def invoke_cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = cli.main(list(args))
        return status, stdout.getvalue(), stderr.getvalue()

    def test_backup_success_and_permissions(self):
        dest_path = Path(self.tmp.name) / "backups" / "backup.db"
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        result = self.store.backup(dest_path)
        self.assertEqual(result["version"], 1)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["destination"], str(dest_path))
        self.assertGreater(result["size_bytes"], 0)
        self.assertTrue(dest_path.is_file())
        
        # Private permissions mode 0600
        mode = dest_path.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_cli_contract_json(self):
        dest_path = Path(self.tmp.name) / "cli_backup.db"
        code, out, err = self.invoke_cli("--state-dir", str(self.state_dir), "backup", str(dest_path), "--json")
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["destination"], str(dest_path.absolute()))
        self.assertEqual(payload["size_bytes"], dest_path.stat().st_size)

    def test_refuse_existing_file(self):
        dest_path = Path(self.tmp.name) / "existing.db"
        dest_path.write_text("initial contents")
        
        with self.assertRaises(ValueError) as cm:
            self.store.backup(dest_path)
        self.assertIn("already exists", str(cm.exception))
        self.assertEqual(dest_path.read_text(), "initial contents")

    def test_refuse_symlink(self):
        target_path = Path(self.tmp.name) / "target.db"
        symlink_path = Path(self.tmp.name) / "symlink.db"
        symlink_path.symlink_to(target_path)
        
        with self.assertRaises(ValueError) as cm:
            self.store.backup(symlink_path)
        self.assertIn("symlink", str(cm.exception))
        self.assertFalse(target_path.exists())

    def test_refuse_aliasing(self):
        source_db = self.state_dir / "state.sqlite3"
        inside_dir = self.state_dir / "backup.db"
        
        with self.assertRaises(ValueError) as cm1:
            self.store.backup(source_db)
        self.assertIn("alias", str(cm1.exception))
        
        with self.assertRaises(ValueError) as cm2:
            self.store.backup(inside_dir)
        self.assertIn("alias", str(cm2.exception))

    def test_cleanup_on_failure(self):
        dest_path = Path(self.tmp.name) / "failed_backup.db"
        with patch("sqlite3.connect", side_effect=sqlite3.OperationalError("disk I/O error")):
            with self.assertRaises(sqlite3.OperationalError):
                self.store.backup(dest_path)
        self.assertFalse(dest_path.exists())

    def test_bounded_timeout_under_lock(self):
        dest_path = Path(self.tmp.name) / "timeout_backup.db"
        
        # Lock source database with an exclusive transaction in DELETE journal mode to force lock contention
        source_db_path = self.state_dir / "state.sqlite3"
        self.store.db.execute("PRAGMA journal_mode=DELETE")
        writer = sqlite3.connect(source_db_path, timeout=0.1)
        writer.execute("BEGIN EXCLUSIVE")
        
        try:
            with self.assertRaises((TimeoutError, sqlite3.OperationalError)):
                self.store.backup(dest_path, timeout=0.1)
            self.assertFalse(dest_path.exists())
        finally:
            writer.rollback()
            writer.close()
            self.store.db.execute("PRAGMA journal_mode=WAL")

    def test_restored_backup_integrity(self):
        dest_path = Path(self.tmp.name) / "integrity_backup.db"
        self.store.backup(dest_path)
        
        # Read backup DB directly without running migrations or Store init
        target_conn = sqlite3.connect(dest_path)
        target_conn.row_factory = sqlite3.Row
        try:
            snapshots = target_conn.execute("SELECT * FROM snapshots WHERE id=?", (self.snap_id,)).fetchall()
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(json.loads(snapshots[0]["payload"]), sample_snapshot())
            
            setting = target_conn.execute("SELECT value FROM settings WHERE key=?", ("consumer:agent-a",)).fetchone()
            self.assertEqual(json.loads(setting[0]), stamp(NOW))
            
            events = target_conn.execute("SELECT * FROM events WHERE id=?", (self.event_id,)).fetchall()
            self.assertEqual(len(events), 1)
            
            checkpoints = target_conn.execute("SELECT * FROM checkpoints WHERE source=?", ("journalctl",)).fetchall()
            self.assertEqual(len(checkpoints), 1)
            self.assertEqual(json.loads(checkpoints[0]["payload"]), {"cursor": "c1"})
        finally:
            target_conn.close()


if __name__ == "__main__":
    unittest.main()
