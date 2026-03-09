# AI 요약 생성 규칙 (corr/script -> data/summaries)

## 1) 목적
- `data/daglo/corr/script`의 스크립트를 기반으로 학습용 요약본을 자동 생성한다.
- 결과물은 파일 단위로 생성하며, 원본 폴더 구조를 그대로 유지한다.
- 생성 형식은 [study_package_output_template.md](./study_package_output_template.md)의 공통 템플릿을 기본으로 따른다.

## 2) 출력 경로 규칙
- 루트: `data/summaries/{AI Agent}/`
- 하위 폴더:
- `data/summaries/{AI Agent}/md/`
- `data/summaries/{AI Agent}/txt/`
- 원본 `data/daglo/corr/script`의 하위 폴더/파일명을 그대로 복제한다.
- 확장자:
- `md` 폴더: `*.md`
- `txt` 폴더: `*.txt`

## 3) 표준 출력 템플릿
- 공통 형식은 [study_package_output_template.md](./study_package_output_template.md)를 따른다.
- 자동 생성/API 방식에서도 상위 5개 섹션 구조를 유지하는 것을 기본값으로 한다.
- 토큰 한도나 길이 제한이 있으면 하위 bullet 수, 시험문제 수, 예시 수를 줄이는 축약형을 허용한다.
- 가능하면 형식 자체를 3개 블록으로 축소하지 말고, 같은 상위 섹션을 유지한 채 밀도를 줄인다.

## 4) 실행 스크립트
- 휴리스틱(로컬) 버전: `generate_ai_summaries.py`
- API 고품질 버전: `generate_ai_summaries_api.py`

### 4-1) 휴리스틱 버전(빠른 생성)
```powershell
py generate_ai_summaries.py `
  --input-root "data/daglo/corr/script" `
  --output-root "data/summaries" `
  --agent-name "GPT-5.3-Codex"
```

### 4-2) API 고품질 버전(권장)
환경변수에 API 키를 넣고 실행한다.

```powershell
$env:OPENAI_API_KEY="YOUR_API_KEY"
py generate_ai_summaries_api.py `
  --input-root "data/daglo/corr/script" `
  --output-root "data/summaries" `
  --agent-name "GPT-5.3-Codex" `
  --model "gpt-5" `
  --temperature 0.2 `
  --overwrite
```

고품질 버전은 긴 원문을 다음 흐름으로 처리한다.
- 1단계: 원문 chunk 단위 요약
- 2단계: chunk 요약 병합(길이 초과 시 재귀 압축)
- 3단계: 최종 템플릿 합성

## 5) 운영 원칙
- 요약 결과는 원본을 덮어쓰지 않고 `data/summaries`에 별도 저장한다.
- 신규/재생성 시에도 폴더 구조 일관성을 유지한다.
- 사용자 요구가 없으면 기존 `corr/script`와 `dict` 파일은 수정하지 않는다.
- API 키를 대화/로그/커밋에 평문으로 남기지 않는다.
- 형식 차이보다 품질 차이를 관리하기 위해, 자동 생성 결과도 Direct Session 산출물과 같은 상위 템플릿을 공유한다.
