import os
import subprocess
import tempfile
import unittest

from diff_service import DiffService


class DiffServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_dir = self.tmp.name
        self.service = DiffService()
        self._git(["init", "-b", "main"])
        self._git(["config", "user.name", "Test User"])
        self._git(["config", "user.email", "test@example.com"])
        self._write("example.txt", "one\n")
        self._git(["add", "example.txt"])
        self._git(["commit", "-m", "initial"])
        self.initial_commit = self._rev_parse("HEAD")
        self._git(["checkout", "-b", "feature/test"])
        self._write("example.txt", "one\ntwo\n")
        self._git(["commit", "-am", "feature change"])
        self.feature_commit = self._rev_parse("HEAD")

    def tearDown(self):
        self.tmp.cleanup()

    def test_generate_commit_diff_returns_parent_and_patch(self):
        result = self.service.generate_commit_diff(self.repo_dir, self.feature_commit)
        self.assertEqual(result.parent_commit, self.initial_commit)
        self.assertIn("+two", result.diff_text)

    def test_generate_commit_diff_raises_for_initial_commit(self):
        with self.assertRaisesRegex(RuntimeError, "has no parents"):
            self.service.generate_commit_diff(self.repo_dir, self.initial_commit)

    def test_generate_pr_diff_uses_merge_base_and_returns_text(self):
        self._git(["checkout", "main"])
        pr = {
            "id": 7,
            "title": "Feature diff",
            "state": "OPEN",
            "source_branch": "feature/test",
            "destination_branch": "main",
            "source_commit": self.feature_commit,
            "destination_commit": self.initial_commit,
            "merge_commit": "",
        }
        result = self.service.generate_pr_diff(pr, self.repo_dir)
        self.assertEqual(result.merge_base, self.initial_commit)
        self.assertEqual(result.resolved_source, self.feature_commit)
        self.assertIn("+two", result.diff_text)

    def test_save_commit_diffs_skips_initial_commit_and_writes_file(self):
        output_dir = os.path.join(self.repo_dir, "out")
        os.makedirs(output_dir, exist_ok=True)
        paths, warnings = self.service.save_commit_diffs(
            self.repo_dir,
            [self.initial_commit, self.feature_commit],
            output_dir,
        )
        self.assertEqual(len(paths), 1)
        self.assertEqual(len(warnings), 1)
        with open(paths[0], "r", encoding="utf-8") as handle:
            self.assertIn("+two", handle.read())

    def _git(self, args):
        subprocess.run(["git", *args], cwd=self.repo_dir, check=True, capture_output=True, text=True)

    def _rev_parse(self, ref):
        result = subprocess.run(
            ["git", "rev-parse", ref],
            cwd=self.repo_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def _write(self, relative_path, content):
        with open(os.path.join(self.repo_dir, relative_path), "w", encoding="utf-8") as handle:
            handle.write(content)


if __name__ == "__main__":
    unittest.main()
