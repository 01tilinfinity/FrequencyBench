# Search-R1 on Frequency Bench

작업 범위: 이 디렉터리 아래에 코드, 공식 checkout, 환경, 다운로드, 입력 사본과 결과를 저장합니다. 원본 `../../data/final/frequency_bench.csv`는 읽기만 합니다.

## 평가 규칙

- 입력: CSV의 `query`를 공백·문장·날짜 변경 없이 공식 Search-R1 템플릿의 Question 뒤에 삽입합니다.
- 정답: CSV의 `value` 문자열 하나. value, frequency, 날짜는 모델 입력에 추가하지 않습니다.
- 모델: `PeterJinGo/SearchR1-nq_hotpotqa_train-qwen2.5-7b-em-ppo-v0.2` (7B base, PPO).
- 검색: `PeterJinGo/wiki-18-corpus`, 원본 `PeterJinGo/wiki-18-e5-index` Flat 인덱스, `intfloat/e5-base-v2`, top-k 3. 공식 GPU 검색 옵션을 사용합니다.
- 생성: 공식 veRL/vLLM 평가 경로를 사용합니다. 검증 시 `do_sample=False`(greedy); 4개 action turn 후 필요한 경우 마지막 생성 1회. 시작 2048, rolling context 4096, 생성당 500, observation 500 tokens.
- 지표: 공식 `qa_em.compute_score_em`의 normalized Exact Match. 숫자 등 별도 정규화, 별칭 확대, LLM judge는 적용하지 않습니다.
- 결과: 전체 micro accuracy, frequency별 accuracy/개수, frequency macro accuracy. 미완료 실행은 `complete=false`로 명시하며 누락 질문을 나열합니다.

CSV에 날짜 없는 질문과 선택된 과거 정답이 있으므로 이 지표는 **CSV value와의 일치율**입니다. 다른 유효한 답이 존재하는지는 자동 판정하지 않습니다.

## 고정 버전과 공식 코드 변경

`data/manifest.json`에 CSV SHA256, 모델 revision과 공식 Git commit을 기록합니다. `reference/`에는 해당 commit의 원본 파일 및 모델 메타데이터가 있습니다.

`integrate.py`는 checkout commit을 검사하고 다음만 변경합니다.

1. `frequency_bench`를 기존 공식 EM 채점으로 연결.
2. 공식 RewardManager의 점수와 최종 응답(검색 관측 포함)을 JSONL에 저장.
3. 검색 요청·원본 결과를 별도 JSONL에 저장하고 HTTP 실패 시 중단.
4. validation의 `drop_last=False`: 마지막 작은 배치도 평가.

추론 알고리즘, 원본 EM 구현과 프롬프트는 유지합니다. GPU 수와 validation batch size는 로컬 자원에 맞추며 기본값은 생성 GPU 0 한 개, batch size 10입니다. 검색은 GPU 1을 사용합니다. 논문 실행과 하드웨어/배치 구성이 같다는 의미는 아니며, 실제 환경 버전은 실행 결과에 기록합니다.

## 준비 상태와 제한

전체 820개 및 클래스당 10개씩 90개 pilot 입력을 준비했습니다. `.venv`는 현재 Parquet 변환용 환경이며, GPU 추론용 패키지 설치·호환성 검증은 아직 수행하지 않았습니다.

현재 디스크 공간으로 원본 검색 인덱스를 저장할 수 없습니다. 알려진 다운로드 크기는 인덱스 64,559,075,373 bytes, 모델 safetensors 30,462,504,632 bytes, 압축 corpus 5,123,307,260 bytes입니다. 압축 해제, 인덱스 조립, Arrow 캐시, 환경 공간이 추가됩니다. `download_assets.py`의 220 GiB는 이를 고려한 보수적 준비 예산이며 정확한 측정 peak가 아닙니다. 파일 삭제나 BM25/ANN 변경은 수행하지 않았습니다.

원본 프로젝트 requirements는 `transformers<4.48`, `vllm<=0.6.3` 등을 사용합니다. 현재 Blackwell GPU에서 이 구형 조합을 그대로 실행할 수 있는지는 미검증입니다. 저장 공간 확보 후 CUDA/PyTorch/vLLM 호환성부터 확인해야 하며, 단순 최신 패키지 교체를 논문 환경의 완전 재현이라고 간주하지 않습니다.

## 실행 순서

프로젝트 루트 기준입니다. 아래 추론 명령은 GPU 환경과 원본 assets가 준비된 이후에 사용합니다.

```bash
# 입력 준비 및 오프라인 검사
evaluation/searchr1/.venv/bin/python evaluation/searchr1/prepare.py --parquet
evaluation/searchr1/.venv/bin/python -m unittest discover -s evaluation/searchr1 -p 'test_*.py'

# 공식 checkout에 데이터 연결 적용 (재실행 가능)
python evaluation/searchr1/integrate.py

# 디스크 요구량 확인; 실제 다운로드는 --execute를 명시
python evaluation/searchr1/download_assets.py
# GPU 환경에서 huggingface_hub 설치 후 실행
python evaluation/searchr1/download_assets.py --execute

# 검색 서버: 별도 터미널, GPU 환경 필요
python evaluation/searchr1/retriever.py --gpus 1

# 평가 명령 미리보기 (GPU 패키지 불필요)
python evaluation/searchr1/run.py --split pilot --dry-run

# GPU 환경에서 점검 → 전체 평가
python evaluation/searchr1/run.py --split pilot --gpus 0
python evaluation/searchr1/run.py --split full --gpus 0
```

공식 checkout이 없는 새 복사본에서는 다음으로 준비합니다.

```bash
git clone https://github.com/PeterGriffinJin/Search-R1.git evaluation/searchr1/upstream
git -C evaluation/searchr1/upstream checkout 598e61bd1d36895726d28a8d06b3a15bed19f5d3
python evaluation/searchr1/integrate.py
```

`run.py`는 공식 `evaluate.sh`의 옵션에서 입력/모델/출력 경로, GPU 수와 batch size만 조정하며 `trainer.val_only=true`를 유지합니다. 공식 초기화가 train 파일을 요구하므로 full.parquet를 그 경로에도 연결하지만 학습하지 않습니다.

실행마다 `results/<split>-<UTC timestamp>/`를 새로 만들며, `manifest.json`, `packages.txt`, `evaluation.log`, `predictions.jsonl`, `retrievals.jsonl`, `summary.json`을 저장합니다. 공식 채점기의 동작을 그대로 보존합니다. 템플릿 자체에 answer 태그가 두 쌍 있어 모델의 최종 답이 없을 때도 예시 Beijing을 추출할 수 있습니다. 이 동작을 테스트로 확인했으며 response_has_answer_tag를 함께 저장합니다. 해당 플래그는 검색 관측을 포함한 응답의 태그 존재 여부이며 별도 정답 판정이 아닙니다. 인프라 오류는 실행 실패·부분 결과로 구분합니다. 검색 로그는 순서대로 기록된 배치 query와 문서이고 sample ID와 일대일로 연결된 형식은 아닙니다. 각 질문의 응답 안에도 실제 주입된 검색 관측이 남습니다.

## 출처

- 논문: https://arxiv.org/pdf/2503.09516
- 공식 평가: https://github.com/PeterGriffinJin/Search-R1/blob/598e61bd1d36895726d28a8d06b3a15bed19f5d3/scripts/nq_hotpotqa/evaluate.sh
- 논문 v0.2 대응: https://github.com/PeterGriffinJin/Search-R1/blob/598e61bd1d36895726d28a8d06b3a15bed19f5d3/docs/experiment_log.md
- 모델: https://huggingface.co/PeterJinGo/SearchR1-nq_hotpotqa_train-qwen2.5-7b-em-ppo-v0.2
