import os
import unittest
from unittest.mock import patch

from vlogshield.storage import MemoryScanStore, mysql_config_from_env


class StorageTests(unittest.TestCase):
    def test_memory_store_records_privacy_safe_scan(self):
        store = MemoryScanStore()
        result = {"score": 55, "grade": "High risk", "risks": [{"name": "GPS"}]}

        record = store.add_scan("jpg", result)
        recent = store.recent_scans()

        self.assertNotIn("filename", record)
        self.assertEqual(record["file_type"], "jpg")
        self.assertEqual(recent, [record])
        self.assertEqual(store.summary()["stored_scans"], 1)
        self.assertEqual(store.summary()["high_risk_scans"], 1)

    def test_mysql_config_from_database_url(self):
        env = {
            "DATABASE_URL": "mysql://scan_user:secret@db.example.test:3307/vlogshield",
        }
        with patch.dict(os.environ, env, clear=True):
            config = mysql_config_from_env()

        self.assertEqual(config["host"], "db.example.test")
        self.assertEqual(config["port"], 3307)
        self.assertEqual(config["user"], "scan_user")
        self.assertEqual(config["password"], "secret")
        self.assertEqual(config["database"], "vlogshield")


if __name__ == "__main__":
    unittest.main()
