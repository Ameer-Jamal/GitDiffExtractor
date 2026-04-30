import tempfile
import unittest

from PyQt5.QtCore import QSettings

from ConfigManager import ConfigManager
from headless_config import HeadlessConfig


class TestConfigManager(ConfigManager):
    ORG_NAME = "GitDiffExtractorHeadlessTests"
    APP_NAME = "GitDiffExtractorHeadlessTests"


class HeadlessConfigTests(unittest.TestCase):
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

    def test_cli_override_beats_app_config(self):
        base = TestConfigManager()
        base.set_provider("bitbucket")
        base.set_github_owner("base-owner")
        config = HeadlessConfig.from_sources(
            base_config=base,
            env={},
            cli_overrides={"provider": "github", "github_owner": "cli-owner"},
        )
        self.assertEqual(config.get_provider(), "github")
        self.assertEqual(config.get_github_owner(), "cli-owner")
        self.assertEqual(config.effective_source_summary()["github_owner"], "override")

    def test_selected_repositories_json_override_roundtrip(self):
        config = HeadlessConfig.from_sources(
            base_config=TestConfigManager(),
            env={"GITDIFFEXTRACTOR_SELECTED_REPOSITORIES_JSON": '[{"owner":"openai","slug":"demo"}]'},
            cli_overrides={},
        )
        self.assertEqual(config.get_selected_repositories()[0]["owner"], "openai")


if __name__ == "__main__":
    unittest.main()
