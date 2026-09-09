"""Persist official RewardManager scores without changing generation or scoring."""

import json
import os
import re
from pathlib import Path


def record_result(data_item, tokenizer, sequences_str, score, valid_response_ids):
    from verl.utils.reward_score import qa_em

    extra = data_item.non_tensor_batch["extra_info"]
    response_text = tokenizer.decode(valid_response_ids)
    record = {
        "sample_id": extra["sample_id"], "source_index": int(extra["source_index"]),
        "query": extra["query"], "value": extra["value"], "frequency": extra["frequency"],
        "prediction": qa_em.extract_solution(sequences_str), "em": float(score),
        "response_with_retrieved_information": response_text,
        "response_has_answer_tag": bool(re.search(r"<answer>.*?</answer>", response_text, re.DOTALL)),
    }
    path = Path(os.environ["SEARCHR1_RESULT_PATH"])
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False) + "\n")
        output.flush()
        os.fsync(output.fileno())


def record_retrieval(queries, payload):
    path = Path(os.environ["SEARCHR1_RESULT_PATH"]).with_name("retrievals.jsonl")
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps({"queries": queries, "response": payload}, ensure_ascii=False) + "\n")
        output.flush()
