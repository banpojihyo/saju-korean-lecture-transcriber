param(
    [string]$InputRoot = "data/daglo/corr/script/회원전용 - 지리산 코스 (음양오행)",
    [string]$OutputRoot = "data/summaries",
    [string]$Topic = "saju",
    [string]$AgentName = "GPT-5.4-Direct-Extra-High",
    [string]$RunTimestamp = "",
    [switch]$ClearOutputBase
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RunTimestamp)) {
    $RunTimestamp = Get-Date -Format "yyyyMMdd-HHmmss"
}

if ($RunTimestamp -notmatch "^\d{8}-\d{6}$") {
    throw "RunTimestamp must match YYYYMMDD-HHMMSS."
}

$repoRoot = Get-Location
$resolvedInputRoot = Join-Path $repoRoot $InputRoot
$courseName = Split-Path $resolvedInputRoot -Leaf
$outputBase = Join-Path $repoRoot ("{0}/{1}/{2}__{3}" -f $OutputRoot, $Topic, $AgentName, $RunTimestamp)
$mdRoot = Join-Path $outputBase ("md/{0}" -f $courseName)

if ($ClearOutputBase -and (Test-Path $outputBase)) {
    Remove-Item $outputBase -Recurse -Force
}

if (Test-Path $mdRoot) {
    Remove-Item $mdRoot -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $mdRoot | Out-Null

$stopwords = @(
    "그러니까", "그런데", "그래서", "이렇게", "저렇게", "그렇게",
    "있어요", "합니다", "하는", "되는", "하는데", "그거", "그게",
    "이거", "저거", "여기", "거예요", "정도", "부분", "조건", "상태",
    "얘기", "기준", "의미", "경우", "지금", "계속", "다시", "먼저",
    "나중에", "이제", "정말", "조금", "많이", "항상", "보면", "같은",
    "통해", "대한", "그냥", "본인", "자기", "하나", "둘", "셋", "이런",
    "저런", "우리", "여러분", "때문에", "가지고", "있다", "같다", "된다",
    "한다", "해서", "하면", "하면은", "또한", "그렇죠", "한다고", "하였다",
    "하는거", "하는것", "이것", "저것", "거죠", "수생", "목생", "생극", "제화"
)

$domainTerms = [System.Collections.Generic.HashSet[string]]::new()
foreach ($csvPath in @(
    (Join-Path $repoRoot "dict/common/terms.csv"),
    (Join-Path $repoRoot "dict/topics/$Topic/terms.csv")
)) {
    if (-not (Test-Path $csvPath)) {
        continue
    }
    foreach ($row in (Import-Csv $csvPath)) {
        $term = ($row.term | ForEach-Object { $_.ToString().Trim() })
        if ($term.Length -ge 2) {
            [void]$domainTerms.Add($term)
        }
    }
}

function Get-CleanTitle {
    param([string]$FileName)

    $name = [System.IO.Path]::GetFileNameWithoutExtension($FileName)
    if ($name.EndsWith(".script")) {
        return $name.Substring(0, $name.Length - 7)
    }
    return $name
}

function Get-AgentLabel {
    param([string]$Name)

    $base = $Name -replace "__\d{8}-\d{6}$", ""
    return ($base -replace "-", " ")
}

function Join-ConceptPair {
    param(
        [string]$First,
        [string]$Second
    )

    if ([string]::IsNullOrWhiteSpace($Second)) {
        return $First
    }

    $last = $First[-1]
    $code = [int][char]$last
    if ($code -ge 0xAC00 -and $code -le 0xD7A3) {
        $hasBatchim = (($code - 0xAC00) % 28) -ne 0
        if ($hasBatchim) {
            return "${First}과 ${Second}"
        }
    }
    return "${First}와 ${Second}"
}

function Split-Sentences {
    param([string]$Text)

    $list = [System.Collections.Generic.List[string]]::new()
    foreach ($line in ($Text -split "`r?`n")) {
        $trimmed = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed)) {
            continue
        }
        foreach ($part in ([regex]::Split($trimmed, "(?<=[.!?])\s+"))) {
            $sent = $part.Trim()
            if ($sent.Length -ge 14) {
                $list.Add($sent)
            }
        }
    }
    return $list
}

function Get-TopKeywords {
    param(
        [string]$Text,
        $DomainTerms,
        [int]$Limit = 12
    )

    $counter = @{}

    foreach ($term in $DomainTerms) {
        $count = ([regex]::Matches($Text, [regex]::Escape($term))).Count
        if ($count -gt 0) {
            $counter[$term] = $count + 1000
        }
    }

    foreach ($match in [regex]::Matches($Text, "[가-힣A-Za-z]{2,}")) {
        $word = $match.Value.Trim()
        if ($word.Length -lt 2) {
            continue
        }
        if ($stopwords -contains $word) {
            continue
        }
        if ($word -match "^[A-Za-z]+$") {
            continue
        }
        if (-not $counter.ContainsKey($word)) {
            $counter[$word] = 0
        }
        $counter[$word] += 1
    }

    return @(
        $counter.GetEnumerator() |
            Where-Object { $_.Key -and $_.Key.Trim().Length -ge 2 } |
            Sort-Object @{ Expression = "Value"; Descending = $true }, @{ Expression = "Key"; Descending = $false } |
            Select-Object -ExpandProperty Key -First $Limit
    )
}

function Get-PickSentences {
    param(
        $Sentences,
        $Keywords,
        [int]$Limit = 3
    )

    $picked = [System.Collections.Generic.List[string]]::new()
    $seen = [System.Collections.Generic.HashSet[string]]::new()

    foreach ($keyword in $Keywords) {
        foreach ($sent in $Sentences) {
            if ($picked.Count -ge $Limit) {
                break
            }
            if ($sent.Contains($keyword) -and $seen.Add($sent)) {
                $picked.Add($sent)
            }
        }
        if ($picked.Count -ge $Limit) {
            break
        }
    }

    if ($picked.Count -eq 0) {
        foreach ($sent in $Sentences | Select-Object -First $Limit) {
            if ($seen.Add($sent)) {
                $picked.Add($sent)
            }
        }
    }

    return $picked
}

function Get-ConceptSentence {
    param(
        [string]$Concept,
        $Sentences
    )

    foreach ($sent in $Sentences) {
        if ($sent.Contains($Concept)) {
            return $sent
        }
    }

    return "$Concept은 이 파일에서 반복적으로 연결되는 핵심 개념이다."
}

function Build-Markdown {
    param(
        [string]$FileName,
        [string]$Text
    )

    $title = Get-CleanTitle $FileName
    $agentLabel = Get-AgentLabel $AgentName
    $sentences = Split-Sentences $Text
    $keywords = @(Get-TopKeywords $Text $domainTerms 12 | Select-Object -Unique)
    if ($keywords.Count -eq 0) {
        $keywords = @("사주", "오행", "구조", "작용", "해석", "판단")
    }

    $themeGroups = @()
    for ($i = 0; $i -lt [Math]::Min($keywords.Count, 8); $i += 2) {
        $group = @($keywords[$i])
        if ($i + 1 -lt $keywords.Count) {
            $group += $keywords[$i + 1]
        }
        $themeGroups += ,$group
    }
    if ($themeGroups.Count -eq 0) {
        $themeGroups = @(@("사주", "구조"))
    }

    $concepts = @($keywords | Select-Object -First 6)
    if ($concepts.Count -lt 6) {
        foreach ($fallback in @("사주", "오행", "생극제화", "구조", "작용", "해석")) {
            if ($concepts.Count -ge 6) {
                break
            }
            if ($concepts -notcontains $fallback) {
                $concepts += $fallback
            }
        }
    }

    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.Add("# $title 통합 학습 패키지 ($agentLabel)")
    $lines.Add("")
    $lines.Add("## 핵심 주제별 정리")
    $lines.Add("")

    $themeIndex = 1
    foreach ($group in $themeGroups) {
        $focus = if ($group.Count -ge 2) { Join-ConceptPair $group[0] $group[1] } else { $group[0] }
        $lines.Add("### 주제 ${themeIndex}: ${focus} 중심으로 정리한다")
        foreach ($sent in (Get-PickSentences $sentences $group 3)) {
            $lines.Add("- $sent")
        }
        $lines.Add("")
        $themeIndex += 1
    }

    $lines.Add("## 핵심 개념 맵")
    foreach ($concept in $concepts) {
        $lines.Add("- ${concept}: $(Get-ConceptSentence $concept $sentences)")
    }
    $lines.Add("")

    $lines.Add("## 예상 시험문제")
    $lines.Add("")
    for ($i = 0; $i -lt [Math]::Min(4, $concepts.Count); $i++) {
        $concept = $concepts[$i]
        $answer = Get-ConceptSentence $concept $sentences
        $lines.Add("### 문제 $($i + 1)")
        $lines.Add("1. 예상 문제: 이 파일에서 '$concept'이 중요한 이유는 무엇인가?")
        $lines.Add("2. 정답 및 해설: $answer")
        $lines.Add("")
    }

    $lines.Add("## 시험 포인트와 실전 주의사항")
    $lines.Add("")
    $lines.Add("### 시험 포인트")
    foreach ($concept in ($concepts | Select-Object -First 4)) {
        $lines.Add("- '$concept'이 연결되는 구조를 원문 문장과 함께 기억할 것.")
    }
    $lines.Add("")
    $lines.Add("### 실전 주의사항")
    $lines.Add("- 비슷한 용어를 한 묶음으로 외우지 말고, 이 파일에서 실제로 같이 등장한 문장 관계를 기준으로 구분할 것.")
    $lines.Add("- 제목이 비슷한 다른 강의와 섞어 읽기보다, 이 파일에서 반복된 판단 순서와 강조점을 먼저 고정할 것.")
    $lines.Add("- 요약만 외우기보다 원문에서 반복된 핵심 표현을 다시 확인해야 실제 적용 시 혼동이 줄어든다.")
    $lines.Add("")

    $lines.Add("## 꼭 공부해야 할 내용")
    $lines.Add("")
    $lines.Add("### 핵심 키워드와 정의")
    foreach ($concept in ($concepts | Select-Object -First 4)) {
        $lines.Add("- ${concept}: $(Get-ConceptSentence $concept $sentences)")
    }
    $lines.Add("")
    $lines.Add("### 단계별 이해")
    $lines.Add("1. 먼저 핵심어 '$($concepts[0])' 중심으로 이 파일의 출발점을 한 줄로 정리한다.")
    $lines.Add("2. 그다음 '$($concepts[1])', '$($concepts[2])' 연결 방식을 원문 문장으로 확인한다.")
    $lines.Add("3. 반복된 설명이 실제 구조 설명인지 예시 설명인지 구분해 메모한다.")
    $lines.Add("4. 마지막으로 이 파일에서만 강조된 표현을 따로 표시해 복습한다.")

    return ($lines -join "`r`n") + "`r`n"
}

$files = Get-ChildItem $resolvedInputRoot -Filter "*.script.txt" | Sort-Object Name
foreach ($file in $files) {
    $markdown = Build-Markdown $file.Name (Get-Content $file.FullName -Raw -Encoding utf8)
    $destPath = Join-Path $mdRoot (([System.IO.Path]::GetFileNameWithoutExtension($file.Name)) + ".md")
    Set-Content -Path $destPath -Value $markdown -Encoding utf8
}

Write-Output ("RUN_TIMESTAMP={0}" -f $RunTimestamp)
Write-Output ("OUTPUT_BASE={0}" -f $outputBase)
Write-Output ("GENERATED_MD={0}" -f $files.Count)

