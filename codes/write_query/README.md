# GLM query 생성

`data/final/frequency_bench.csv`의 각 행에서 `entity`와 `property`를 읽어
`{"entity": "...", "relation": "..."}` 형태의 user 메시지로 전달합니다.
value, 날짜 등 다른 컬럼은 LLM 입력에 포함하지 않습니다.

1. `prompt/query.txt`에 프롬프트를 작성합니다. 파일은 현재 비어 있습니다.
   내용 전체가 system 메시지로 전달되며, 변수 치환은 하지 않습니다.
   모델이 query 한 개만 텍스트로 답하도록 출력 형식도 직접 지정해 주세요.
   응답 텍스트는 앞뒤 공백만 제거하여 `query` 컬럼에 저장합니다.
2. 프로젝트 루트 `.env`에 `GLM_API_KEY`를 설정합니다.
   선택적으로 `GLM_MODEL`, `GLM_BASE_URL`도 설정할 수 있습니다.
3. 프로젝트 루트에서 실행합니다.

```bash
pip install -r codes/write_query/requirements.txt
python codes/write_query/generate.py --dry-run
python codes/write_query/generate.py --limit 5
python codes/write_query/generate.py --resume
```

기본 모델은 `glm-4.7`, API 주소는 `https://api.z.ai/api/paas/v4/`입니다.
[Z.AI 공식 API 문서](https://docs.z.ai/api-reference/llm/chat-completion)에 따라
OpenAI 호환 API를 호출하고 thinking은 비활성화합니다.
`--model`, `--base-url`, `--prompt`, `--input`, `--output`으로 변경할 수 있습니다.
기본 입출력 및 프롬프트 경로는 실행 디렉터리와 무관합니다.
명시적으로 전달한 상대 경로는 현재 실행 디렉터리를 기준으로 합니다.

기본 결과 파일은 `data/final/frequency_bench_queries.csv`이며,
원본 컬럼과 행 순서를 유지하고 `query` 컬럼을 추가합니다.
성공한 행마다 저장합니다. API 일시 오류는 SDK가 최대 3번 재시도하고,
최종 실패 또는 빈 응답/잘린 응답이 발생하면 중단합니다.
기존 결과가 있으면 `--resume` 없이 덮어쓰지 않습니다.
`--resume`은 기존 결과가 입력의 앞부분과 일치하는지 확인한 후 이어 실행합니다.
프롬프트·모델 설정은 이어 실행 시 동일하게 유지하세요. 변경하여 다시 생성하려면
새로운 `--output` 경로를 사용하세요.
`--limit`은 이번 실행에서 새로 생성할 최대 행 수입니다.
`--dry-run`은 다음 요청을 출력하며 API 키/호출 없이 동작합니다.

기타 옵션은 `python codes/write_query/generate.py --help`에서 확인할 수 있습니다.
