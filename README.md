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
  --dict-dir ".\dict"
```

필요하면 입출력 루트를 직접 지정할 수 있습니다.

```powershell
py correct_daglo_file.py `
  --source-file "<raw 경로의 txt>" `
  --dict-dir ".\dict" `
  --input-root "data/daglo/raw" `
  --output-root "data/daglo/corr"
```

## 4) 여러 파일 일괄 교정 예시

```powershell
Get-ChildItem "data/daglo/raw" -Recurse -Filter *.txt | ForEach-Object {
  py correct_daglo_file.py `
    --source-file $_.FullName `
    --dict-dir ".\dict" `
    --input-root "data/daglo/raw" `
    --output-root "data/daglo/corr"
}
```

## 5) 주제별 사전 분리 운영 (권장)

`correct_daglo_file.py`는 `--dict-dir`를 지원하므로 주제별 폴더 분리가 가능합니다.

```text
dict/
  common/{replace.csv,terms.csv}
  topics/network/{replace.csv,terms.csv}
  topics/security/{replace.csv,terms.csv}
  topics/math/{replace.csv,terms.csv}
  topics/philosophy/{replace.csv,terms.csv}
  topics/essay/{replace.csv,terms.csv}
```

현재는 `--dict-dir` 하나를 선택해 실행합니다.

```powershell
py correct_daglo_file.py `
  --source-file "<raw 경로의 txt>" `
  --dict-dir ".\dict\topics\network"
```

## 6) 기존 output(TXT/SRT) 후처리 + dict 갱신

`refine_output_dict.py`는 `output` 폴더의 TXT/SRT를 사전 기반으로 보정하고,
새로운 용어/오인식 후보를 `dict/replace.csv`, `dict/terms.csv`에 추가합니다.

```powershell
py refine_output_dict.py `
  --output-dir ".\output" `
  --dict-dir ".\dict"
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
