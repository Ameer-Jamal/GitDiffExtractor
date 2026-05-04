import os
import tempfile
import unittest

from PyQt5.QtCore import QSettings

from ConfigManager import ConfigManager


class TestConfigManager(ConfigManager):
    ORG_NAME = "RepoLensTests"
    APP_NAME = "RepoLensTests"


class ConfigManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        settings = QSettings(TestConfigManager.ORG_NAME, TestConfigManager.APP_NAME)
        settings.clear()

    def test_selected_repositories_roundtrip(self):
        cfg = TestConfigManager()
        repos = [
            {"id": "1", "owner": "etqdev", "slug": "mt-backend"},
            {"id": "2", "owner": "etqdev", "slug": "mt-frontend"},
        ]
        cfg.set_selected_repositories(repos)
        self.assertEqual(cfg.get_selected_repositories(), repos)

    def test_cached_discovery_roundtrip(self):
        cfg = TestConfigManager()
        repos = [{"id": "1", "owner": "etqdev", "slug": "mt-backend"}]
        cfg.set_cached_discovered_repositories("bitbucket", "etqdev", repos)
        cached, ts = cfg.get_cached_discovered_repositories("bitbucket", "etqdev")
        self.assertEqual(cached, repos)
        self.assertGreater(ts, 0.0)


if __name__ == "__main__":
    unittest.main()
