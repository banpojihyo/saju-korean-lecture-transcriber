# AI 요약 생성 규칙 (corr/script -> data/ai)

## 1) 목적
- `data/daglo/corr/script`의 스크립트를 기반으로 학습용 요약본을 자동 생성한다.
- 결과물은 파일 단위로 생성하며, 원본 폴더 구조를 그대로 유지한다.
- 생성 형식은 사용자가 요청한 3개 블록 구조를 반드시 따른다.

## 2) 출력 경로 규칙
- 루트: `data/ai/{AI Agent}/`
- 하위 폴더:
- `data/ai/{AI Agent}/md/`
- `data/ai/{AI Agent}/txt/`
- 원본 `data/daglo/corr/script`의 하위 폴더/파일명을 그대로 복제한다.
- 확장자:
- `md` 폴더: `*.md`
- `txt` 폴더: `*.txt`

## 3) 파일별 생성 템플릿
각 출력 파일은 아래 3개 섹션을 포함한다.

1. `🔖 핵심 주제별로 나눠서 정리해줘`
- 주요 주제를 그룹화
- 각 주제를 `###` 헤더로 구분
- 주제별 세부는 Bullet points 요약

2. `📑 시험문제를 만들어줘`
- 핵심 개념 5개 선정
- 각 개념마다:
- 예상 문제(객관식 또는 단답형)
- 정답 및 해설

3. `📗 꼭 공부해야 할 내용을 알려줘`
- 핵심 키워드 정의
- 복잡한 개념/흐름의 단계별 설명

## 4) 실행 스크립트
- 파일: `generate_ai_summaries.py`
- 기본 실행:
```powershell
py generate_ai_summaries.py `
  --input-root "data/daglo/corr/script" `
  --output-root "data/ai" `
  --agent-name "GPT-5.3-Codex"
```

## 5) 운영 원칙
- 요약 결과는 원본을 덮어쓰지 않고 `data/ai`에 별도 저장한다.
- 신규/재생성 시에도 폴더 구조 일관성을 유지한다.
- 사용자 요구가 없으면 기존 `corr/script`와 `dict` 파일은 수정하지 않는다.
