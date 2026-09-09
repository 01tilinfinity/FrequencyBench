import importlib.util
import json
import unittest
from protocol import BASE, ROOT, PREFIX, adapt, load_rows, pilot_rows, summarize
from run import build_command


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.digest = load_rows(ROOT / "data/final/frequency_bench.csv")
        spec = importlib.util.spec_from_file_location("official_em", BASE / "upstream/verl/utils/reward_score/qa_em.py")
        cls.em = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.em)

    def test_all_queries_unchanged_and_only_query_in_prompt(self):
        for row in self.rows:
            example = adapt(row)
            self.assertEqual(example["prompt"], [{"role": "user", "content": PREFIX + row["query"] + "\n"}])
            self.assertEqual(example["reward_model"]["ground_truth"]["target"], [row["value"]])
        row = dict(self.rows[0], value="GOLD_ONLY_SENTINEL", start_time="DATE_ONLY_SENTINEL", frequency="FREQUENCY_ONLY_SENTINEL")
        content = adapt(row)["prompt"][0]["content"]
        self.assertNotIn("GOLD_ONLY_SENTINEL", content)
        self.assertNotIn("DATE_ONLY_SENTINEL", content)
        self.assertNotIn("FREQUENCY_ONLY_SENTINEL", content)

    def test_pilot_stratification(self):
        from collections import Counter
        pilot = pilot_rows(self.rows)
        self.assertEqual(len(pilot), 90)
        self.assertEqual(set(Counter(r["frequency"] for r in pilot).values()), {10})
        self.assertEqual(pilot, pilot_rows(self.rows))
        self.assertEqual(len({r["sample_id"] for r in pilot}), len(pilot))

    def test_official_metric_and_template_extraction(self):
        transcript = PREFIX + "Q?\n<think>reason</think><answer>The Paris.</answer>"
        answer = self.em.extract_solution(transcript)
        self.assertEqual(answer, "The Paris.")
        self.assertEqual(self.em.em_check(answer, ["paris"]), 1)
        self.assertEqual(self.em.em_check("Paris and London", ["Paris"]), 0)
        self.assertEqual(self.em.em_check("10", ["10.0"]), 0)
        # Preserve and expose the upstream template-fallback behavior.
        self.assertEqual(self.em.extract_solution(PREFIX + "Q?"), "Beijing")
        self.assertIsNone(self.em.extract_solution("No answer tags"))

    def test_complete_and_incomplete_summaries(self):
        expected = [{"sample_id": "a", "frequency": "X"}, {"sample_id": "b", "frequency": "X"},
                    {"sample_id": "c", "frequency": "Y"}]
        records = [{"sample_id": "a", "em": 1}, {"sample_id": "b", "em": 0}, {"sample_id": "c", "em": 1}]
        result = summarize(expected, records)
        self.assertTrue(result["complete"])
        self.assertAlmostEqual(result["micro_accuracy"], 2 / 3)
        self.assertEqual(result["macro_accuracy"], .75)
        partial = summarize(expected, records[:1])
        self.assertFalse(partial["complete"])
        self.assertIsNone(partial["macro_accuracy"])
        self.assertEqual(partial["missing_ids"], ["b", "c"])
        with self.assertRaises(ValueError):
            summarize(expected, records + records[:1])

    def test_native_command_uses_eval_only(self):
        command = build_command("pilot", 1, 10, BASE / "results/test")
        self.assertIn("+trainer.val_only=true", command)
        self.assertIn("max_turns=4", command)
        self.assertIn("retriever.topk=3", command)
        self.assertIn("data.max_response_length=500", command)
        self.assertFalse(any("$" in arg for arg in command))
        self.assertIn("data.val_files=" + str(BASE / "data/pilot.parquet"), command)

    def test_serialized_inputs_cover_original(self):
        examples = [json.loads(line) for line in (BASE / "data/full.jsonl").read_text().splitlines()]
        self.assertEqual(len(examples), len(self.rows))
        self.assertEqual([e["extra_info"]["query"] for e in examples], [r["query"] for r in self.rows])
        manifest = json.loads((BASE / "data/manifest.json").read_text())
        self.assertEqual(manifest["input_sha256"], self.digest)


if __name__ == "__main__":
    unittest.main()
