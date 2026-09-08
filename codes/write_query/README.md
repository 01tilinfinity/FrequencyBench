# Query 생성

`data/final/frequency_bench.csv`의 각 행에서 `entity`와 `property`를 읽어
`{"entity": "...", "relation": "..."}` 형태로 GPT-5.6 Luna에 전달합니다.
value, 날짜 등 다른 컬럼은 LLM 입력에 포함하지 않습니다.
`prompt/query.txt` 전체가 system 메시지로 전달되며 변수 치환은 하지 않습니다.
모델은 reasoning 없이 영어 질문 한 문장만 생성하도록 설정합니다.

프로젝트 루트 `.env`에 `OPENAI_API_KEY`를 설정하고 실행합니다.

```bash
pip install -r codes/write_query/requirements.txt
python codes/write_query/generate.py --dry-run
python codes/write_query/generate.py
```

**별도 결과 CSV를 만들지 않고 기존 입력 CSV에 `query` 컬럼을 추가합니다.**
기존 컬럼 값과 행 순서를 보존하고, 성공한 행마다 임시 파일을 통한 원자적 교체로 저장합니다.
저장 중 원본에 외부 변경이 감지되면 중단합니다. 실행 중에는 입력 CSV를 다른 작업으로 수정하지 마세요.
`tqdm`에 저장 완료한 query 수, 전체 행 수, 처리 속도, 예상 남은 시간이 표시됩니다.
기본 동시 요청 수는 4이며 `--workers`로 변경할 수 있습니다.

중단 후에는 같은 모델과 프롬프트로 재개합니다.

```bash
python codes/write_query/generate.py --resume
```

`--resume`은 이미 채워진 query를 유지하고, 행 위치와 무관하게 빈 query만 생성합니다.
기존 query가 있는데 `--resume`을 지정하지 않으면 덮어쓰지 않고 중단합니다.
API 일시 오류는 SDK가 최대 3번 재시도합니다. 최종 실패, 잘린 응답, 빈 응답,
여러 줄 또는 물음표로 끝나지 않는 응답은 저장하지 않고 중단합니다.
API 오류나 사용자 중단 시 이미 CSV에 저장된 query는 유지됩니다.

`--limit 5`는 이번 실행에서 최대 5개만 새로 생성합니다.
`--dry-run`은 다음 요청을 보여주며 API 호출과 파일 수정을 하지 않습니다.
`--input`, `--prompt`, `--model`, `--workers`, `--max-tokens`, `--timeout`, `--max-retries`를 조정할 수 있습니다.
기본 모델은 `gpt-5.6-luna`, API는 OpenAI Chat Completions, `reasoning_effort`는 `none`입니다.
기본 경로는 실행 디렉터리와 무관하며 명시한 상대 경로는 실행 디렉터리 기준입니다.
