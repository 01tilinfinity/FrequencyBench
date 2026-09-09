# Frequency benchmark 최종 데이터

`frequency_bench.csv`: UTF-8 CSV, 820행. 샘플 단위는 entity–property 한 쌍이며 중복 쌍은 없습니다.

## 추출 규칙

- Plot 1과 동일한 `data/raw/wd_scan/timelines.before_overlapfix`의 151,547개 타임라인을 사용합니다.
- 유효 property 379개를 데이터 수 내림차순, 동률이면 PID 숫자 오름차순으로 정렬하고 상위 190개를 우선합니다. 누적 데이터 50%가 아니라 property 개수 50%(올림)입니다.
- 각 Frequency에서 우선 후보를 최대 100개 비복원 랜덤 추출하고, 부족할 때만 나머지 property의 같은 클래스에서 보충합니다. 전체 후보가 부족하면 전부 사용합니다.
- Python `random.Random(42)` 사용. 파일은 PID 숫자 오름차순, 행은 원본 순서로 후보를 구성합니다. 아래 클래스 순서대로 전체 클래스의 쌍을 먼저 `random.sample`로 선택합니다.
- 이어서 같은 RNG로 각 선택 타임라인의 이력 하나를 균등 선택하여 value를 정합니다. 따라서 서로 다른 value 자체의 균등 추출은 아닙니다. 같은 value의 가장 이른 start 이력을 택하며, 날짜 동률은 원본 첫 항목의 end를 유지합니다. 클래스별 결과를 같은 RNG로 shuffle합니다.
- property별 균등 할당은 하지 않습니다. 기존 라벨/필터/미래 날짜 정책을 변경하지 않습니다.

## 컬럼

| 컬럼 | 의미 |
|---|---|
| entity_id / entity | Entity QID / 자연어 라벨 |
| property_id / property | Property PID / 자연어 라벨 |
| value_id / value | Value QID / 자연어 라벨. 숫자·문자열·시간 리터럴은 value_id가 비고 value에 원래 값을 보존 |
| value_unit | Quantity의 단위 라벨. 명시적 무단위는 unitless, 비-Quantity는 빈칸 |
| frequency | 원본 Frequency 클래스 |
| frequency_days | 전체 entity–property 타임라인의 양수인 연속 start-to-start 간격 중앙값(일) |
| start_time / end_time | 선택된 value의 가장 이른 이력 한 건의 짝지어진 날짜. 종료일 누락은 빈칸 |
| query | entity와 property 라벨만 입력하여 GPT-5.6 Luna로 생성한 영어 질문. 참고 날짜는 추가하지 않음 |

`end_time - start_time`은 `frequency_days`와 같을 필요가 없습니다. 날짜는 전체 타임라인의 양 끝이 아닙니다.
연·월 정밀도 날짜도 원본에서 YYYY-MM-DD로 정규화되어 있으므로 01-01/월초를 실제 일 단위 정밀도로 해석하면 안 됩니다.
동일 value의 반복 이력과 원본 timeline에 저장된 deprecated 항목은 추가 제거하지 않았습니다. Frequency 계산과 선택 이력의 모집단이 다를 수 있는 원본 특성을 유지합니다.
숫자의 단위는 원시 TSV statement ID를 Wikidata claim과 대조해 보강했습니다. 통화 환산은 하지 않으며 수치의 상·하한과 나머지 qualifier는 이 간결한 CSV에 싣지 않습니다.
라벨은 en → mul → ko → 기타 언어 순의 캐시를 사용합니다. 단위·라벨은 수집 당시 고정 스냅샷이 아닌 보강 조회값입니다. 원본의 사실 정확성이나 미래 예정값을 추가 검증/정정한 데이터는 아닙니다.

## 클래스별 후보와 최종 수

| Frequency | 상위 190 후보 | 나머지 후보 | 우선 추출 | 추가 추출 | 최종 |
|---|---:|---:|---:|---:|---:|
| A-Day | 20 | 0 | 20 | 0 | 20 |
| A-Few-Days | 495 | 3 | 100 | 0 | 100 |
| A-Week | 567 | 1 | 100 | 0 | 100 |
| A-Few-Weeks | 1,153 | 3 | 100 | 0 | 100 |
| A-Month | 1,561 | 2 | 100 | 0 | 100 |
| A-Few-Months | 4,294 | 19 | 100 | 0 | 100 |
| A-Year | 34,087 | 33 | 100 | 0 | 100 |
| A-Few-Years | 79,744 | 147 | 100 | 0 | 100 |
| Many-Years | 29,255 | 163 | 100 | 0 | 100 |

이번 실행은 모든 추가 추출이 0개입니다. A-Day는 전체 20개, 나머지 8개 클래스는 각각 100개입니다.

## 우선 property 목록 (순위순)

P54, P39, P17, P2632, P6, P27, P102, P937, P488, P127, P137, P1308, P286, P31, P26, P6087, P281, P551, P1037, P118, P276, P361, P1410, P106, P4791, P138, P531, P159, P195, P463, P410, P3872, P169, P749, P279, P608, P1352, P8047, P1998, P36, P1376, P366, P793, P1416, P451, P1268, P466, P1075, P2802, P371, P35, P123, P115, P598, P468, P241, P5769, P264, P449, P3975, P2043, P98, P166, P2295, P2139, P527, P5817, P3362, P532, P734, P797, P1454, P92, P1618, P5096, P7779, P176, P1545, P4100, P197, P291, P879, P618, P426, P512, P140, P8413, P1532, P2896, P611, P3300, P945, P1114, P97, P119, P859, P1342, P559, P2317, P708, P1344, P126, P1083, P582, P1435, P8247, P210, P511, P1001, P504, P505, P607, P12363, P915, P800, P38, P2046, P2868, P742, P3983, P1030, P3460, P7938, P831, P1875, P2388, P84, P634, P1027, P3320, P237, P1132, P669, P1066, P1313, P121, P272, P609, P641, P57, P175, P1110, P1830, P2283, P6872, P2047, P178, P217, P664, P1327, P2124, P2838, P3301, P3342, P3438, P10308, P86, P750, P1029, P1640, P2109, P2257, P2825, P47, P85, P612, P1071, P2505, P2758, P2813, P5995, P50, P186, P194, P495, P798, P2499, P4345, P12452, P122, P156, P161, P162, P725, P825, P837, P1535, P1824, P5607, P81

## 재현 및 검증

- 생성: `python codes/preprocessing/build_final.py --write`
- 오프라인 재검증: `python codes/preprocessing/build_final.py --check --offline`
- 보강 캐시: `data/raw/wikidata_label_cache.json`, `data/raw/wikidata_statement_quantity_cache.json`
- 원본 파일명+내용 결합 SHA256: `bee931a2126679f3c3365e43004b87d9ed8d97b521aa074c6c485a441736fd64`
- query 컬럼 추가 전 CSV SHA256: `638f779f963bdb002344b40b76ef2c42fd6d2790e2a092c6077b5e143b06a9c8`

## Query 생성

`python codes/write_query/generate.py`로 기존 CSV에 `query` 컬럼을 추가합니다.
생성 중에는 `tqdm`으로 저장 완료한 행 수를 확인할 수 있고, 중단 후에는 `--resume`으로 빈 query만 채웁니다.
프롬프트와 실행 옵션은 `codes/write_query/README.md`를 참고하세요.
위 데이터 추출 재현 명령은 query 생성 전 데이터에 대한 것이며, query는 별도의 API 생성 단계입니다.
