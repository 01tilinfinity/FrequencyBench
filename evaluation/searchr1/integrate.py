"""Apply narrowly scoped data-routing and logging hooks to the pinned official checkout."""

import subprocess

from protocol import BASE, UPSTREAM_REVISION


def replace_once(path, before, after):
    source = path.read_text()
    if after in source:
        return
    if source.count(before) != 1:
        raise ValueError(f"Upstream changed; cannot safely patch {path}")
    path.write_text(source.replace(before, after))


def main():
    upstream = BASE / "upstream"
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=upstream, text=True).strip()
    if revision != UPSTREAM_REVISION:
        raise ValueError(f"Expected upstream {UPSTREAM_REVISION}, got {revision}")
    main_file = upstream / "verl/trainer/main_ppo.py"
    replace_once(main_file, "if data_source in ['nq',", "if data_source in ['frequency_bench', 'nq',")
    replace_once(main_file,
        "            reward_tensor[i, valid_response_length - 1] = score",
        "            from result_hook import record_result\n"
        "            record_result(data_item, self.tokenizer, sequences_str, score, valid_response_ids)\n"
        "            reward_tensor[i, valid_response_length - 1] = score")
    generation = upstream / "search_r1/llm_agent/generation.py"
    replace_once(generation,
        "        return requests.post(self.config.search_url, json=payload).json()",
        "        response = requests.post(self.config.search_url, json=payload, timeout=120)\n"
        "        response.raise_for_status()\n"
        "        result = response.json()\n"
        "        from result_hook import record_retrieval\n"
        "        record_retrieval(queries, result)\n"
        "        return result")
    trainer = upstream / "verl/trainer/ppo/ray_trainer.py"
    replace_once(trainer,
        "                                         shuffle=False,\n                                         drop_last=True,",
        "                                         shuffle=False,\n                                         drop_last=False,")
    print("Official generation/scoring retained; data routing, logging and final-batch retention added.")


if __name__ == "__main__":
    main()
