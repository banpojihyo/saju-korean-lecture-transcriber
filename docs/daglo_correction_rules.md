# Daglo 교정 규칙서 (2026-03-08 기준)

## 1) 목표
- 미교정 Daglo 스크립트를 `replace.csv`, `terms.csv` 기반으로 자연스럽게 교정한다.
- 문맥상 어색할 수 있는 치환은 자동 적용하지 않고 보수적으로 건너뛴다.
- 교정 과정에서 확인된 유효 치환/용어를 사전에 반영해 다음 교정을 쉽게 만든다.

## 2) 기본 입출력 구조
- 입력: `data/daglo/raw/**/*.txt`
- 출력:
- `data/daglo/corr/corrected/**/*.corrected.txt`
- `data/daglo/corr/script/**/*.script.txt`
- `data/daglo/corr/changes/**/*.changes.txt`

## 3) 교정 규칙(핵심)
- 교정 규칙 소스:
- `dict/replace.csv`
- `correct_daglo_file.py`의 `manual_pairs()`
- 적용 순서:
- `wrong` 문자열 길이가 긴 규칙부터 우선 적용(부분 중첩 오적용 방지)
- 문맥 필터:
- `PAIR_CONTEXT_RULES` 대상(예: `귀신->기신`, `무반->무관`, `고친->고층`)은 include/exclude 문맥을 모두 통과해야 적용
- 4자 이하 한글 치환은 다음 2가지 모두 만족 시에만 적용
- 어절 경계(`is_word_boundary`) 만족
- 주변 ±120자 내 도메인 키워드(`DOMAIN_CONTEXT_KEYWORDS`) 존재
- 필터를 통과하지 못한 치환은 적용하지 않고 `skipped by context`로 기록

## 4) 자연스러운 교정 원칙
- 일괄 치환 금지: 문맥 근거 없는 짧은 토큰 치환은 하지 않는다.
- 의미 충돌 가능성이 있으면 보수적으로 유지한다.
- 사주/명리 도메인 문맥에서만 의미가 확정되는 치환만 적용한다.
- 반복 확인된 ASR 오인식은 `dict/topics/<theme>/replace.csv`에 우선 반영한다.
- `관여예요`, `정관여예요`처럼 문장형으로만 의미가 확정되는 항목은 단일 단어 치환보다 phrase-level exact replacement를 우선한다.
- 예: `상관은 사례 정관여예요. -> 상관은 살의 정관이에요.`, `기포면은 이게 정관여예요. -> 기토면은 이게 정관이에요.`
- 강의 도입부처럼 여러 토큰이 한꺼번에 무너진 문장은 짧은 토큰 단위로 억지 복원하지 않고, 문맥이 닫힌 opener 문장을 exact phrase로 교정한다.
- 예: `오늘은 청년 들어가기 전에 사조의 공 공 군에 대한 해석을 할 거예요. -> 오늘은 천간 들어가기 전에 사주의 궁에 대한 해석을 할 거예요.`
- 같은 이유로 일반 한국어와 충돌할 수 있는 표현도 문맥이 닫힌 구문이면 exact phrase로만 교정한다.
- 예: `이렇게 닥터이면은 -> 이렇게 박토이면은`은 토의 `박토/후토` 대비 문맥에서만 쓰고, `닥터 지바고` 같은 일반 표현은 건드리지 않는다.
- `관묵 -> 갑목`, `항만조습 -> 한난조습`, `모기 개입 -> 목이 개입`처럼 반복 검증된 고신뢰 도메인 오인식은 짧은 토큰 필터보다 우선 적용할 수 있다.
- `cg -> 시지`처럼 짧은 영문/혼합 토큰 오인식도 도메인상 의미가 확정되면 `FORCE_DOMAIN_REPLACEMENTS`와 `replace.csv`에 함께 넣어 우선 적용한다.
- `감묵/관묵 -> 갑목`, `토국수/목국토 -> 토극수/목극토`, `심금 -> 신금`은 무조건 치환하지 않는다. `PAIR_CONTEXT_RULES`로 사주/오행 문맥을 확인한 뒤에만 적용한다.
- `기포 -> 기토`, `배수 -> 계수`는 일반 한국어에서는 다른 뜻이 가능하므로 기본적으로 무조건 치환하지 않는다.
- 다만 `dict/topics/saju`를 사용하면서 입력 루트가 `data/daglo/raw`인 경우에는 현재 사주 코퍼스 특성을 반영해 `기포 -> 기토`, `배수 -> 계수`를 더 공격적으로 적용할 수 있다.
- `생무기/사무기/생모기/사모기/수생무기/수생모기/관무기`처럼 `목/갑목`이 `무기/모기`로 잘못 인식된 패턴은 일반 토큰 치환보다 phrase-level exact replacement를 우선한다.
- 위 패턴들과 그에 대응하는 phrase-level exact replacement도 `dict/topics/saju` + `data/daglo/raw` 조합에서는 현재 코퍼스 기준으로 공격적으로 적용할 수 있다.
- 반대로 그 외 경로에서는 동일 규칙을 무조건 적용하지 않고, 주변 ±120자 내 사주/오행 도메인 키워드가 확인될 때만 적용한다.
- 연결형(`요수생무기`, `수생모기지는`)은 exact phrase를 추가해 보완한다.
- 예: `생무기인지 -> 생목인지`, `사무기인지 -> 사목인지`, `관무기 -> 갑목이`, `수생무기 -> 수생목이`
- `생극제화`처럼 도메인 핵심 복합어는 띄어쓰기/ASR 변형을 한 용어로 정규화한다.
- 예: `생극 재화`, `생극 제화`, `생극재화`, `생국제화`, `생급 재화`, `생극 재활`, `생각제화` -> `생극제화`
- 복합어 정규화 후 조사/어미가 어색하게 붙은 후행 형태도 함께 정리한다.
- 예: `생극제화을 -> 생극제화를`
- `오행생극재화`처럼 앞 단어가 붙은 복합어도 함께 정규화해 `오행생극제화`로 유지한다.
- 특히 `심금 -> 신금`은 `심금을 울리다` 같은 일반 한국어 표현과 충돌하므로, `울리다/가슴/마음/노래` 문맥이 보이면 자동 치환하지 않는다.

## 5) 사전(`replace.csv`, `terms.csv`) 업데이트 규칙
- 기본값은 자동 업데이트(옵션 `--no-update-dict` 미사용 기준)
- `replace.csv`:
- 이번 실행에서 실제 적용된 `(wrong, right)`만 신규 추가
- 중복 pair는 추가하지 않음
- 조사/어미가 붙은 문장형 교정은 `replace.csv`에만 넣고, `terms.csv`에는 넣지 않는다.
- `terms.csv`:
- 적용된 `right`에서 용어 후보를 정규화 후 추가
- 공백 포함, 숫자만, 한글 미포함, 길이 비정상(2자 미만/20자 초과) 제외
- 조사/어미 꼬리(`TRAILING_SUFFIXES`) 제거 후 후보화
- 일반 서술형 종결(`REJECT_ENDINGS`)은 제외
- 따라서 `한난조습`, `갑목` 같은 단일 용어는 `terms.csv` 대상이지만, `목이 개입`, `조건인 거예요`, `그게 관이에요` 같은 문장형 보정은 `terms.csv` 대상이 아니다.
- `시지`, `진술축미`, `한난조습`, `생목`, `사목`처럼 정규 용어로 환원되는 치환 결과는 `terms.csv`에 유지한다.
- `생극제화`, `오행생극제화`처럼 반복 출현하는 핵심 복합 용어도 `terms.csv`에 유지한다.

## 6) `.changes` 기록 규칙
- 블록 시작 헤더: `[commit - YYYY-MM-DD HH:MM:SS]`
- 예: `[121b9b6 - 2026-03-08 21:27:13]`
- 각 블록은 아래 구조 유지:
- `source`, `output`, `script_only_output`
- 집계 메타(`applied_rules`, `changed_chars`, `dict_replace_added`, `context_skipped_*` 등)
- `[applied replacements]` (필수)
- `[skipped by context]`, `[dict replace added]`, `[dict terms added]` (해당 시)
- 재교정 시 원칙:
- 기존 블록을 덮어쓰지 않고 하단에 새 블록을 추가(이력 보존)

## 7) 실행 절차
1. 대상 선정
- 신규(raw만 있고 corrected 없음) 또는 재교정 대상 파일 목록을 확정
2. 교정 실행
- 파일별 `correct_daglo_file.py` 실행
3. 결과 검토
- `changes`의 `applied/skipped` 확인
- 문맥상 부자연스러운 치환이 없는지 샘플 점검
4. 사전 반영 확인
- `dict/replace.csv`, `dict/terms.csv` 신규 항목 점검
5. 이력 보존
- 재교정은 `.changes` 기존 내용을 유지한 채 새 블록 append

## 8) 단일 파일 실행 예시
```powershell
py correct_daglo_file.py `
  --source-file "data/daglo/raw/회원전용 - 기본다이제스트 (계룡산 등반)/기본 다이제스트 04 - 오행의 한난조습 2.txt" `
  --dict-dir ".\dict\topics\saju" `
  --input-root "data/daglo/raw" `
  --output-root "data/daglo/corr"
```

## 9) 신규 raw 일괄 실행 예시(미교정 대상만)
```powershell
$rawRoot = "data/daglo/raw"
$corrRoot = "data/daglo/corr/corrected"

Get-ChildItem $rawRoot -Recurse -Filter *.txt | ForEach-Object {
  $rel = Resolve-Path $_.FullName | ForEach-Object { $_.Path.Substring((Resolve-Path $rawRoot).Path.Length).TrimStart('\') }
  $corr = Join-Path $corrRoot ([System.IO.Path]::ChangeExtension($rel, ".corrected.txt"))
  if (-not (Test-Path $corr)) {
    py correct_daglo_file.py `
      --source-file $_.FullName `
      --dict-dir ".\dict\topics\saju" `
      --input-root "data/daglo/raw" `
      --output-root "data/daglo/corr"
  }
}
```

## 10) 체크리스트
- 문맥 기반 필터(`PAIR_CONTEXT_RULES`, `DOMAIN_CONTEXT_KEYWORDS`) 유지 확인
- 짧은 한글 치환의 경계/문맥 검사 유지 확인
- 사전 자동 업데이트 결과 검토
- `.changes` 이력 append 원칙 준수 확인
