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
