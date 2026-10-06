"""Exercise runtime/checker path boundaries with synthetic files and no providers."""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "skills" / "generate-inquiry-shard"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # Dataclasses resolve annotation metadata through the module registry.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Import the actual engine, but make a provider call impossible even when the
# OpenAI package happens to be installed. The engine never reads the env file.
with patch.dict(sys.modules, {"openai": types.ModuleType("openai")}):
    ENGINE = load_module("_context_path_test_engine", ROOT / "ic_engine.py")
CHECKER = load_module("_context_path_test_checker", BUNDLE / "check_shard.py")


class ShardContextPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="inquiry-context-path-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / "Shards" / "sample"
        self.contexts = self.folder / "contexts"
        self.contexts.mkdir(parents=True)
        self.file = self.folder / "sample.json"
        self.private = self.root / "private.md"
        self.private.write_text("SYNTHETIC PRIVATE CONTENT", encoding="utf-8")
        self.data = {
            "title": "Synthetic test",
            "source": "Synthetic test input",
            "source_brief": "synthetic test input",
            "central": "A question?",
            "nodes": [{"id": "CENTRAL", "text": "A question?", "parent": None, "notes": "Root question"}],
            "edges": [],
        }
        self.central_context = "# CENTRAL: A question?\n" + "context " * 310
        (self.contexts / "CENTRAL.md").write_text(self.central_context, encoding="utf-8")
        self.write_shard()

    def write_shard(self):
        self.file.write_text(json.dumps(self.data), encoding="utf-8")

    def add_node(self, node_id):
        self.data["nodes"].append({"id": node_id, "text": "A child question?", "parent": "CENTRAL", "notes": "Child question"})
        self.data["edges"].append({"from": "CENTRAL", "to": node_id, "weight": 0.5})
        self.write_shard()

    def assert_rejected_before_context_reads(self):
        original = Path.read_text
        context_reads = []

        def tracked_read(path, *args, **kwargs):
            if path.suffix == ".md":
                context_reads.append(path)
                raise AssertionError("A context read occurred before unsafe paths were rejected")
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", tracked_read):
            with self.assertRaises(ValueError):
                ENGINE.load_shard(str(self.file))
            errors, _ = CHECKER.check(self.file)
            self.assertTrue(errors, "Unsafe shard was reported READY")
        self.assertEqual(context_reads, [])

    def test_valid_contexts_load_and_check(self):
        shard = ENGINE.load_shard(str(self.file))
        self.assertEqual(shard.nodes["CENTRAL"].context, self.central_context)
        self.assertEqual(CHECKER.check(self.file), ([], []))

    def test_absolute_id_is_rejected_before_any_context_read(self):
        self.add_node(str(self.private.with_suffix("")))
        self.assert_rejected_before_context_reads()

    def test_traversal_and_cross_platform_path_ids_are_rejected(self):
        for node_id in ("../../../private", "../CENTRAL", "folder/CENTRAL", r"..\private", r"C:\private", ".", "..", "CENTRAL\n", ""):
            with self.subTest(node_id=node_id):
                self.data["nodes"] = self.data["nodes"][:1]
                self.data["edges"] = []
                self.add_node(node_id)
                self.assert_rejected_before_context_reads()

    def test_nonstring_ids_are_rejected_before_context_reads(self):
        for node_id in (None, 123, True, ["CENTRAL"], {"id": "CENTRAL"}):
            with self.subTest(node_id=node_id):
                self.data["nodes"] = self.data["nodes"][:1]
                self.data["edges"] = []
                self.add_node(node_id)
                self.assert_rejected_before_context_reads()

    def test_context_file_symlink_cannot_escape_contexts(self):
        self.add_node("CHILD")
        (self.contexts / "CHILD.md").symlink_to(self.private)
        self.assert_rejected_before_context_reads()

    def test_context_file_symlink_cannot_escape_to_other_shard_file(self):
        self.add_node("CHILD")
        sibling = self.folder / "other.md"
        sibling.write_text("SYNTHETIC NON-CONTEXT FILE", encoding="utf-8")
        (self.contexts / "CHILD.md").symlink_to(sibling)
        self.assert_rejected_before_context_reads()

    def test_context_directory_symlink_cannot_escape_shard(self):
        shutil.rmtree(self.contexts)
        outside = self.root / "outside-contexts"
        outside.mkdir()
        (outside / "CENTRAL.md").write_text(self.central_context, encoding="utf-8")
        self.contexts.symlink_to(outside, target_is_directory=True)
        self.assert_rejected_before_context_reads()

    def test_context_directory_symlink_cannot_expose_shard_siblings(self):
        shutil.rmtree(self.contexts)
        (self.folder / "CENTRAL.md").write_text("SYNTHETIC NON-CONTEXT FILE", encoding="utf-8")
        self.contexts.symlink_to(self.folder, target_is_directory=True)
        self.assert_rejected_before_context_reads()

    def test_symlink_to_another_file_inside_contexts_is_allowed(self):
        self.add_node("CHILD")
        (self.contexts / "CHILD.md").symlink_to(self.contexts / "CENTRAL.md")
        self.assertEqual(ENGINE.load_shard(str(self.file)).nodes["CHILD"].context, self.central_context)
        errors, _ = CHECKER.check(self.file)
        self.assertEqual(errors, [])

    def test_missing_context_keeps_existing_runtime_fallback(self):
        (self.contexts / "CENTRAL.md").unlink()
        self.assertEqual(ENGINE.load_shard(str(self.file)).nodes["CENTRAL"].context, "")
        self.assertTrue(CHECKER.check(self.file)[0])

    def test_all_bundled_shards_remain_valid_and_loadable(self):
        files = sorted((ROOT / "Shards").rglob("*.json"))
        self.assertTrue(files)
        for file in files:
            with self.subTest(shard=file.name):
                errors, warnings = CHECKER.check(file)
                self.assertEqual(errors, [])
                self.assertEqual(warnings, [])
                self.assertTrue(ENGINE.load_shard(str(file)).nodes)

    def test_checker_bundle_remains_portable(self):
        copied = self.root / "copied-skill"
        copied.mkdir()
        for name in ("check_shard.py", "_shard_paths.py"):
            shutil.copyfile(BUNDLE / name, copied / name)
        result = subprocess.run(
            [sys.executable, "-B", str(copied / "check_shard.py"), str(self.file)],
            cwd=self.root, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("READY:", result.stdout)

    def test_claude_checker_and_helper_match_canonical_bundle(self):
        mirror = ROOT / ".claude" / "skills" / "generate-inquiry-shard"
        for name in ("check_shard.py", "_shard_paths.py"):
            self.assertEqual((BUNDLE / name).read_bytes(), (mirror / name).read_bytes())


if __name__ == "__main__":
    unittest.main()
