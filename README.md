# daglo-script-corrector

Daglo로 1차 전사된 강의 스크립트를 CSV 사전 기반으로 문맥 교정하는 CLI 프로젝트입니다.

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
  common/{replace.csv,terms.csv}
  topics/saju/{replace.csv,terms.csv}
  topics/network/{replace.csv,terms.csv}
  topics/security/{replace.csv,terms.csv}
  topics/math/{replace.csv,terms.csv}
  topics/philosophy/{replace.csv,terms.csv}
  topics/philosophy_east/{replace.csv,terms.csv}
  topics/philosophy_west/{replace.csv,terms.csv}
  topics/vocal/{replace.csv,terms.csv}
  topics/essay/{replace.csv,terms.csv}
```

- `dict/topics/saju`는 기존 사주 사전을 기준으로 초기화되어 있습니다.
- `dict/common`은 전 주제 공통 오탈자/용어를 담는 용도입니다.
- `dict/topics/<theme>`는 주제 특화 사전을 담는 용도입니다.
- `dict/topics/philosophy_east`, `dict/topics/philosophy_west`를 권장하며, `dict/topics/philosophy`는 통합형(호환)입니다.
- `correct_daglo_file.py`와 `refine_output_dict.py`의 기본 `--dict-dir`는 `dict/common`입니다.

`run_topic_correction.py`를 사용하면 `common + topic`을 병합해 교정할 수 있습니다.
교정 중 새로 발견된 항목은 기본적으로 해당 topic 사전에만 반영됩니다.

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

## 7) Legacy: 로컬 전사 스크립트

향후 재사용을 위해 로컬 전사 스크립트는 `legacy/transcribe_videos.py`로 이동했습니다.

```powershell
py legacy/transcribe_videos.py `
  --input-dir "N:\개인\영상\멀리보다\회원전용 - 한라산 코스 (십성론)" `
  --output-dir ".\output" `
  --sample-only `
  --model large-v3 `
  --language ko
```

## 8) Gemini로 학습 패키지 일괄 생성

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

## 9) 통합 AI 파이프라인 (OpenAI/Gemini 선택)

`run_ai_pipeline.py`는 `ai summaries`와 `study pack` 요구를 병합한 통합 실행 파일입니다.

- 공급자 선택: `--provider openai|gemini`
- 출력 스타일 선택: `--style summary|study-pack|merged`
- 주제 선택: `--topic saju|security|network|math|philosophy_east|philosophy_west|vocal|...`
- 출력 형식 선택: `--output-format md|txt|both`

출력 경로:

- `data/ai_outputs/<agent-name>/<provider>/<style>/md/**/*.md`
- `data/ai_outputs/<agent-name>/<provider>/<style>/txt/**/*.txt`

OpenAI 예시:

```powershell
$env:OPENAI_API_KEY="YOUR_OPENAI_API_KEY"
py run_ai_pipeline.py `
  --provider openai `
  --style merged `
  --topic saju `
  --input-root "data/daglo/corr/script" `
  --output-root "data/ai_outputs" `
  --agent-name "Unified-AI" `
  --model "gpt-5" `
  --output-format both `
  --max-files 3 `
  --overwrite
```

Gemini 예시:

```powershell
$env:GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
py run_ai_pipeline.py `
  --provider gemini `
  --style merged `
  --topic saju `
  --input-root "data/daglo/corr/script" `
  --output-root "data/ai_outputs" `
  --agent-name "Unified-AI" `
  --model "gemini-2.5-flash" `
  --output-format both `
  --max-files 3 `
  --overwrite
```

참고:

- 기존 `generate_ai_summaries*.py`, `generate_study_pack_gemini.py`는 호환을 위해 그대로 유지됩니다.
