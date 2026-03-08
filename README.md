# saju-translater

한국어 강의 영상 폴더에서 음성을 스크립트화(TXT/SRT)하는 간단한 CLI입니다.

## 1) 설치

```powershell
py -m pip install -r requirements.txt
```

## 2) 샘플 1개만 테스트

```powershell
py transcribe_videos.py `
  --input-dir "N:\개인\영상\멀리보다\회원전용 - 한라산 코스 (십성론)" `
  --output-dir ".\output" `
  --sample-only `
  --model large-v3 `
  --language ko
```

`--model large-v3`는 정확도 우선(느림)입니다.
빠른 점검이 필요하면 `--model small --max-seconds 180` 같은 식으로 먼저 테스트하세요.

## 3) 여러 파일 처리

```powershell
py transcribe_videos.py `
  --input-dir "N:\개인\영상\멀리보다\회원전용 - 한라산 코스 (십성론)" `
  --output-dir ".\output" `
  --max-files 5 `
  --model large-v3 `
  --language ko
```

## 출력물

- `<영상파일명>.txt`
- `<영상파일명>.srt`

## 4) 기존 output 자동 보정 + dict 자동 갱신

`dict/replace.csv`, `dict/terms.csv`를 기반으로 `output`의 TXT/SRT를 보정하고,
자주 등장하는 용어/오인식 후보를 사전에 자동 추가합니다.

```powershell
py refine_output_dict.py `
  --output-dir ".\output" `
  --dict-dir ".\dict"
```

먼저 변경 내용을 확인만 하려면:

```powershell
py refine_output_dict.py --dry-run
```

## 5) Daglo 교정본 생성 (`raw` -> `corr`)

Daglo 원본 텍스트는 `data/daglo/raw`, 교정 결과는 `data/daglo/corr`를 사용합니다.
생성 파일은 아래 하위 폴더로 자동 분리됩니다.

- `data/daglo/corr/corrected` (`*.corrected.txt`)
- `data/daglo/corr/script` (`*.script.txt`)
- `data/daglo/corr/changes` (`*.changes.txt`)

```powershell
py correct_daglo_file.py `
  --source-file "data/daglo/raw/회원전용 - 기본다이제스트 (계룡산 등반)/기본 다이제스트 04 - 오행의 한난조습 2.txt" `
  --dict-dir ".\\dict"
```

필요하면 루트 경로를 직접 지정할 수 있습니다.

```powershell
py correct_daglo_file.py `
  --source-file "<raw 경로의 txt>" `
  --input-root "data/daglo/raw" `
  --output-root "data/daglo/corr"
```
