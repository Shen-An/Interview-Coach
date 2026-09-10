import json
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend import retrieval
from backend.kb import KBManager


class _Cfg:
    provider = "test"
    model = "fake"


class _FakeLlm:
    cfg = _Cfg()

    def __init__(self, artifact=None, delay=0):
        self.artifact = artifact or {
            "topic": ["Agent"],
            "questions": [{"q": "如何保证幂等？", "company": "", "frequency": "高频"}],
            "scenarios": [], "events": [], "coding": [],
        }
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.guard = threading.Lock()

    def chat(self, *_args, **_kwargs):
        with self.guard:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(self.delay)
        with self.guard:
            self.active -= 1
        return json.dumps(self.artifact, ensure_ascii=False)


class WikiPersistenceTests(unittest.TestCase):
    def _manager(self, root):
        resource = Path(__file__).resolve().parents[1] / "kb"
        manager = KBManager(resource, Path(root) / "kb")
        manager.seed()
        return manager

    def test_import_keeps_raw_when_compilation_fails(self):
        with TemporaryDirectory() as tmp:
            manager = self._manager(tmp)
            llm = _FakeLlm({"topic": [], "questions": [], "scenarios": [], "events": [], "coding": []})
            with self.assertRaises(ValueError):
                manager.import_daily(llm, "empty.md", "raw evidence")
            self.assertEqual((manager.raw_dir / "import__empty.md").read_text(encoding="utf-8"), "raw evidence")
            self.assertFalse((manager.compiled_dir / "import__empty.json").exists())

    def test_import_serializes_write_transactions(self):
        with TemporaryDirectory() as tmp:
            manager = self._manager(tmp)
            llm = _FakeLlm(delay=0.04)
            errors = []

            def run(index):
                try:
                    manager.import_daily(llm, f"item-{index}.md", f"raw {index}")
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            self.assertEqual(llm.max_active, 1)

    def test_import_flows_from_raw_to_compiled_catalog(self):
        with TemporaryDirectory() as tmp:
            manager = self._manager(tmp)
            artifact = {
                "topic": ["pipeline-e2e"],
                "questions": [{
                    "q": "如何验证 raw compiled catalog 链路？",
                    "company": "",
                    "frequency": "高频",
                    "platform": "TestPlatform",
                }],
                "scenarios": [], "events": [], "coding": [],
            }
            result = manager.import_daily(_FakeLlm(artifact), "pipeline.md", "raw evidence")
            store = retrieval.load(manager.compiled_dir, manager.data_kb)
            catalog = retrieval.catalog(store, query="raw compiled catalog")

            self.assertTrue((manager.raw_dir / result["raw_file"]).exists())
            self.assertTrue((manager.compiled_dir / result["compiled_file"]).exists())
            self.assertEqual(catalog["total"], 1)
            self.assertEqual(catalog["items"][0]["platform"], "TestPlatform")
            self.assertEqual(catalog["items"][0]["topic"], "pipeline-e2e")

    def test_atomic_write_preserves_destination_when_replace_fails(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "UPDATES.md"
            target.write_text("old content", encoding="utf-8")
            with patch("backend.kb.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    KBManager._atomic_write_text(target, "new content")
            self.assertEqual(target.read_text(encoding="utf-8"), "old content")
            self.assertEqual(list(target.parent.glob(".UPDATES.md.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
