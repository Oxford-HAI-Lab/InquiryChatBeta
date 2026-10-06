"""Exercise publication boundaries using only disposable synthetic repositories."""

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("release", Path(__file__).resolve().parents[1] / "tools/prepare_release.py")
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class ReleasePackagingTests(unittest.TestCase):
    def test_private_and_unreviewed_paths_rejected(self):
        for name in ["env", "sessions/chat.json", "PhilosophyPod/xiaozhi-esp32/sdkconfig",
                     "static/.env.production", "design/mockups/image.png", "private-notes.md",
                     "static/../../env", "docs/settings.local.json", "dist/release.tar"]:
            with self.subTest(name=name), self.assertRaises(release.ReleaseError):
                release.validate_path(name)

    def test_secret_values_not_in_diagnostics(self):
        key = "sk-" + "x" * 40
        with self.assertRaises(release.ReleaseError) as caught:
            release.inspect_contents({"README.md": key.encode()})
        self.assertIn("README.md", str(caught.exception))
        self.assertNotIn(key, str(caught.exception))

    def test_private_paths_rejected_regardless_of_case(self):
        for name in ["static/Env", "static/.ENV.production", "docs/Sessions/chat.json",
                     "PhilosophyPod/xiaozhi-esp32/SDKCONFIG", "docs/notes.BAK",
                     "docs/.DS_STORE", "static/.VENV.old-copy/config"]:
            with self.subTest(name=name), self.assertRaises(release.ReleaseError):
                release.validate_path(name)

    def test_archive_exact_and_deterministic(self):
        contents = {"README.md": b"Example\n", "static/app.js": b"// example\n"}
        self.assertEqual(release.build_archive(contents), release.build_archive(dict(reversed(list(contents.items())))))

    def test_ignored_settings_never_enter_candidate_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.git(root, "init", "-q")
            (root / ".gitignore").write_text("env\nsessions/\n")
            (root / "env").write_text("private synthetic content")
            (root / "README.md").write_text("public")
            self.assertEqual(set(release.read_candidates(root)), {".gitignore", "README.md"})

    def test_force_added_settings_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.git(root, "init", "-q")
            (root / "env").write_text("synthetic")
            self.git(root, "add", "env")
            with self.assertRaisesRegex(release.ReleaseError, "Private/generated"):
                release.read_candidates(root, staged=True)

    def test_staged_archive_uses_index_not_working_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.git(root, "init", "-q")
            (root / "README.md").write_text("reviewed")
            self.git(root, "add", "README.md")
            (root / "README.md").write_text("unstaged")
            self.assertEqual(release.read_candidates(root, staged=True), {"README.md": b"reviewed"})

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.git(root, "init", "-q")
            try:
                (root / "README.md").symlink_to("outside-file")
            except OSError as exc:
                self.skipTest(f"Symbolic links unavailable: {exc}")
            with self.assertRaises(release.ReleaseError):
                release.read_candidates(root)
            self.git(root, "add", "README.md")
            with self.assertRaises(release.ReleaseError):
                release.read_candidates(root, staged=True)

    def test_unmerged_index_rejected_in_both_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.git(root, "init", "-q")
            (root / "README.md").write_text("conflicted working content")
            blob = subprocess.run(
                ["git", "-C", str(root), "hash-object", "-w", "--stdin"],
                input=b"synthetic public content", check=True, capture_output=True,
            ).stdout.decode().strip()
            entries = "".join(f"100644 {blob} {stage}\tREADME.md\n" for stage in (1, 2, 3))
            subprocess.run(["git", "-C", str(root), "update-index", "--index-info"],
                           input=entries.encode(), check=True, capture_output=True)
            for staged in (False, True):
                with self.subTest(staged=staged), self.assertRaisesRegex(release.ReleaseError, "unmerged"):
                    release.read_candidates(root, staged=staged)

    @staticmethod
    def git(root, *args):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
