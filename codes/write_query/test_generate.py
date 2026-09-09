import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import generate


class InPlaceGenerationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "bench.csv"
        self.original = 'entity,property,value\n"A, B",position held,"x,y"\nØrn,place of detention,z\nThird,net profit,10\n'
        self.path.write_text(self.original, encoding="utf-8")

    def test_fill_preserves_values_order_and_existing_queries(self):
        fields, rows, digest = generate.load_input(self.path)
        original_rows = [dict(row) for row in rows]
        rows[1]["query"] = "Where was Ørn detained?"
        digest = generate.save_csv(self.path, fields + ["query"], rows, digest)
        pending = generate.pending_indices(rows, resume=True)
        self.assertEqual(pending, [0, 2])
        args = SimpleNamespace(input=self.path, limit=None, workers=2)
        with patch.object(generate, "generate_query", side_effect=lambda client, args, messages: "What is requested?"), patch.object(generate, "tqdm"):
            saved = generate.fill_queries(None, args, "prompt", fields + ["query"], rows, digest, pending)
        self.assertEqual(saved, 2)
        updated_fields, updated, _ = generate.load_input(self.path)
        self.assertEqual(updated_fields, fields + ["query"])
        self.assertEqual([{k:row[k] for k in fields} for row in updated], original_rows)
        self.assertEqual(updated[1]["query"], "Where was Ørn detained?")
        self.assertTrue(all(row["query"] for row in updated))
        with self.assertRaises(ValueError):
            generate.pending_indices(updated, resume=False)
        self.assertEqual(generate.pending_indices(updated, resume=True), [])

    def test_failed_replace_leaves_original_intact(self):
        fields, rows, digest = generate.load_input(self.path)
        with patch.object(generate.os, "replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                generate.save_csv(self.path, fields + ["query"], rows, digest)
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_external_edits_are_not_overwritten(self):
        fields, rows, digest = generate.load_input(self.path)
        self.path.write_text("External edit", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed during generation"):
            generate.save_csv(self.path, fields + ["query"], rows, digest)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "External edit")

    def test_api_failure_preserves_checkpoint_and_can_resume(self):
        fields, rows, digest = generate.load_input(self.path)
        args = SimpleNamespace(input=self.path, limit=None, workers=1)
        with patch.object(generate, "generate_query", side_effect=["What position did A, B hold?", RuntimeError("provider failure")]), patch.object(generate, "tqdm"):
            with self.assertRaisesRegex(ValueError, "data row 2"):
                generate.fill_queries(None, args, "prompt", fields, rows, digest, [0, 1, 2])
        _, updated, _ = generate.load_input(self.path)
        self.assertEqual(updated[0]["query"], "What position did A, B hold?")
        self.assertEqual(generate.pending_indices(updated, resume=True), [1, 2])
        self.assertEqual(len(updated), 3)


if __name__ == "__main__":
    unittest.main()
