# daglo-script-corrector

Daglo로 1차 전사된 강의 스크립트를 사전 + 파일별 override 기반으로 문맥 교정하는 CLI 프로젝트입니다.

## 1) 설치

```powershell
py -m pip install -r requirements.txt
```

## 2) 입력/출력 구조

- 입력: `data/daglo/raw/**/*.txt`
- 출력:
- `data/daglo/corr/corrected/**/*.corrected.txt`
- `data/daglo/corr/script/**/*.script.txt`
- `data/daglo/corr/changes/**/*.changes.txt`

## 3) 단일 파일 교정

```powershell
py correct_daglo_file.py `
  --source-file "data/daglo/raw/회원전용 - 기본다이제스트 (계룡산 등반)/기본 다이제스트 04 - 오행의 한난조습 2.txt" `
  --dict-dir ".\dict\topics\saju"
```

필요하면 입출력 루트를 직접 지정할 수 있습니다.

```powershell
py correct_daglo_file.py `
  --source-file "<raw 경로의 txt>" `
  --dict-dir ".\dict\topics\<theme>" `
  --input-root "data/daglo/raw" `
  --output-root "data/daglo/corr"
```

## 4) 여러 파일 일괄 교정 예시

```powershell
Get-ChildItem "data/daglo/raw" -Recurse -Filter *.txt | ForEach-Object {
  py correct_daglo_file.py `
    --source-file $_.FullName `
    --dict-dir ".\dict\topics\<theme>" `
    --input-root "data/daglo/raw" `
    --output-root "data/daglo/corr"
}
```

## 5) 주제별 사전 분리 운영

현재 사전 구조는 아래처럼 분리되어 있습니다.

```text
dict/
  common/{replace.csv,terms.csv,file_overrides.jsonl,term_stopwords.txt}
  topics/saju/{replace.csv,terms.csv,file_overrides.jsonl,term_stopwords.txt}
  topics/network/{replace.csv,terms.csv,file_overrides.jsonl,term_stopwords.txt}
  topics/security/{replace.csv,terms.csv,file_overrides.jsonl,term_stopwords.txt}
  topics/math/{replace.csv,terms.csv,file_overrides.jsonl,term_stopwords.txt}
  topics/philosophy/{replace.csv,terms.csv,file_overrides.jsonl,term_stopwords.txt}
  topics/philosophy_east/{replace.csv,terms.csv,file_overrides.jsonl,term_stopwords.txt}
  topics/philosophy_west/{replace.csv,terms.csv,file_overrides.jsonl,term_stopwords.txt}
  topics/vocal/{replace.csv,terms.csv,file_overrides.jsonl,term_stopwords.txt}
  topics/essay/{replace.csv,terms.csv,file_overrides.jsonl,term_stopwords.txt}
```

- `dict/topics/saju`는 기존 사주 사전을 기준으로 초기화되어 있습니다.
- `dict/common`은 전 주제 공통 오탈자/용어를 담는 용도입니다.
- `dict/topics/<theme>`는 주제 특화 사전을 담는 용도입니다.
- `replace.csv`는 반복적으로 재사용할 수 있는 전역 치환 규칙만 둡니다.
- `replace.csv`는 기본형 pair 중심으로 두고, common 조사형(`은/는`, `이/가`, `을/를`, `이라고요` 등)은 런타임에 자동 확장 적용합니다.
- 기존처럼 조사형을 직접 여러 줄로 적어둔 csv도 그대로 호환됩니다.
- `file_overrides.jsonl`은 특정 파일에서만 써야 하는 문장형 exact replacement를 둡니다.
- `term_stopwords.txt`는 common 또는 topic 단위로 자동 `terms.csv` 갱신 시 들어가면 안 되는 일반어 stopword를 둡니다.
- `dict/topics/philosophy_east`, `dict/topics/philosophy_west`를 권장하며, `dict/topics/philosophy`는 통합형(호환)입니다.
- `correct_daglo_file.py`와 `refine_output_dict.py`의 기본 `--dict-dir`는 `dict/common`입니다.

`run_topic_correction.py`를 사용하면 `common + topic`을 병합해 교정할 수 있습니다.
교정 중 새로 발견된 항목은 기본적으로 해당 topic 사전에만 반영되지만, 자동 추가는 짧고 재사용 가능한 pair/term 위주로만 제한됩니다.

```powershell
py run_topic_correction.py `
  --topic network `
  --source-file "<raw 경로의 txt>" `
  --input-root "data/daglo/raw" `
  --output-root "data/daglo/corr"
```

필요하면 기존 방식대로 특정 사전 폴더 하나만 직접 지정할 수도 있습니다.

```powershell
py correct_daglo_file.py `
  --source-file "<raw 경로의 txt>" `
  --dict-dir ".\dict\topics\network"
```

## 6) 기존 output(TXT/SRT) 후처리 + dict 갱신

`refine_output_dict.py`는 `output` 폴더의 TXT/SRT를 사전 기반으로 보정하고,
새로운 용어/오인식 후보를 지정한 `--dict-dir` 아래 csv에 추가합니다.

```powershell
py refine_output_dict.py `
  --output-dir ".\output" `
  --dict-dir ".\dict\topics\saju"
```

변경 사항만 먼저 보려면:

```powershell
py refine_output_dict.py --dry-run
```

## 7) 의심 구간 일괄 추출

`extract_correction_candidates.py`는 `corr/script`를 훑으면서 아직 남아 있는 known-wrong phrase를 파일/줄/대략 timestamp와 함께 뽑아줍니다. `replace.csv`, `manual_pairs()`, `file_overrides.jsonl`에 있는 known-wrong phrase를 함께 참고합니다.

```powershell
py extract_correction_candidates.py `
  --topic saju `
  --target "회원전용 - 지리산 코스 (음양오행)" `
  --script-root "data/daglo/corr/script" `
  --corrected-root "data/daglo/corr/corrected"
```

필요하면 regex도 추가할 수 있습니다.

```powershell
py extract_correction_candidates.py `
  --topic saju `
  --target "회원전용 - 지리산 코스 (음양오행)" `
  --regex "천관|장관|월감|가평 영리"
```

## 8) script 검토 marker -> override 변환

`corr/script/*.script.txt`를 검토하면서 아래와 같은 marker 줄을 넣어두면:

```text
@@ override: 사모기에 한 모기 개입 => 사목에 한목이 개입
```

`script_review_to_overrides.py`가 해당 `script` 경로를 기준으로 raw 상대경로를 자동 추론해서 `dict/topics/<topic>/file_overrides.jsonl`에 반영합니다.

```powershell
py script_review_to_overrides.py `
  --topic saju `
  --script-file "data/daglo/corr/script/회원전용 - 지리산 코스 (음양오행)/06. 음양오행.script.txt" `
  --clean-markers
```

- marker 형식: `@@ override: <wrong> => <right>`
- `--clean-markers`를 주면 반영 후 marker 줄을 script 파일에서 제거합니다.
- 동일한 `path + wrong`가 이미 있으면 `right`를 업데이트합니다.

즉 workflow는 `script 검토 -> marker 기록 -> override 변환 -> raw 재생성` 순서로 가져가면 됩니다.

## 9) Legacy: 로컬 전사 스크립트

향후 재사용을 위해 로컬 전사 스크립트는 `legacy/transcribe_videos.py`로 이동했습니다.

```powershell
py legacy/transcribe_videos.py `
  --input-dir "N:\개인\영상\멀리보다\회원전용 - 한라산 코스 (십성론)" `
  --output-dir ".\output" `
  --sample-only `
  --model large-v3 `
  --language ko
```

## 10) Gemini로 학습 패키지 일괄 생성

`generate_study_pack_gemini.py`는 스크립트 텍스트를 순회하면서 아래 3가지를 한 번에 생성합니다.

- 핵심 주제별 정리
- 예상 시험문제 5개(정답/해설 포함)
- 꼭 공부해야 할 핵심 요약 노트

출력 경로는 `data/study_packs/<agent-name>/{md,txt}`이며, 입력 폴더 구조를 그대로 유지합니다.

```powershell
$env:GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
py generate_study_pack_gemini.py `
  --input-root "data/daglo/corr/script" `
  --output-root "data/study_packs" `
  --agent-name "Gemini-Study-Pack" `
  --topic security `
  --model "gemini-2.5-flash" `
  --overwrite
```

주요 옵션:

- `--topic <name>`: `dict/topics/<name>/terms.csv`를 자동 사용
- `--terms-path <csv>`: 사용할 용어 사전을 직접 지정
- `--max-files <N>`: 테스트용 소량 실행
- `--sleep-sec <float>`: 요청 사이 대기(쿼터 관리)

## 11) 통합 AI 파이프라인 (OpenAI/Gemini 선택)

`run_ai_pipeline.py`는 `ai summaries`와 `study pack` 요구를 병합한 통합 실행 파일입니다.

- 공급자 선택: `--provider openai|gemini`
- 출력 스타일 선택: `--style summary|study-pack|merged`
- 주제 선택: `--topic saju|security|network|math|philosophy_east|philosophy_west|vocal|...`
- 출력 형식 선택: `--output-format md|txt|both`
- 최종 출력 보강 재시도: `--final-retries <N>` (기본 3, 중간 끊김 대응)
- 중간 끊김 재시도 시 `max_output_tokens`를 자동으로 단계적으로 늘려 재생성합니다.
- API 한도 초과(429/RESOURCE_EXHAUSTED) 발생 시, 작업을 취소하지 않고 해당 시점까지 생성된 내용을 `partial` 결과로 저장합니다.
- 기본값은 OpenAI 기준 `openai + gpt-5.3-chat-latest + saju + merged + both`입니다.
- 권장 기본 세팅은 `--agent-name "GPT-5.3-Chat-Latest"`, `--chunk-chars 6000`, `--max-output-tokens 5000`, `--final-retries 3`입니다.
- `--temperature`는 Gemini나 OpenAI 호환 커스텀 엔드포인트용 옵션으로 두고, 공식 OpenAI API 호출에서는 기본적으로 보내지 않습니다.

출력 경로:

- `data/summaries/<topic>/<agent-name>__<run-timestamp>/md/**/*.md`
- `data/summaries/<topic>/<agent-name>__<run-timestamp>/txt/**/*.txt`
- `run-timestamp` 형식은 `YYYYMMDD-HHMMSS`이고, 기본값은 실행 시각입니다.
- 필요하면 `--run-timestamp "20260312-202500"`처럼 명시해서 같은 출력 폴더를 재사용할 수 있습니다.

OpenAI 예시:

```powershell
$env:OPENAI_API_KEY="YOUR_OPENAI_API_KEY"
py run_ai_pipeline.py `
  --provider openai `
  --style merged `
  --topic saju `
  --input-root "data/daglo/corr/script" `
  --output-root "data/summaries" `
  --agent-name "GPT-5.3-Chat-Latest" `
  --run-timestamp "20260312-202500" `
  --model "gpt-5.3-chat-latest" `
  --output-format both `
  --chunk-chars 6000 `
  --max-output-tokens 5000 `
  --final-retries 3 `
  --max-files 3 `
  --overwrite
```

OpenAI 메모:

- 공식 OpenAI 기본 경로(`https://api.openai.com/v1`)에서는 `temperature`를 기본적으로 보내지 않습니다.
- `gpt-5.3-chat-latest` 같은 최신 OpenAI 모델은 `temperature` 미지원 응답을 반환할 수 있습니다.

Gemini 예시:

```powershell
$env:GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
py run_ai_pipeline.py `
  --provider gemini `
  --style merged `
  --topic saju `
  --input-root "data/daglo/corr/script" `
  --output-root "data/summaries" `
  --agent-name "Unified-AI" `
  --run-timestamp "20260312-202500" `
  --model "gemini-2.5-flash" `
  --output-format both `
  --max-files 3 `
  --overwrite
```

Gemini 메모:

- `--temperature`는 Gemini 쪽에서 그대로 사용됩니다.

참고:

- 기존 `generate_ai_summaries*.py`, `generate_study_pack_gemini.py`는 호환을 위해 그대로 유지됩니다.
