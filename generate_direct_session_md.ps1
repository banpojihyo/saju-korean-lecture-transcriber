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
$manifestRoot = Join-Path $outputBase "rewrite_manifest"
$manifestPath = Join-Path $manifestRoot ("{0}.jsonl" -f $courseName)

if ($ClearOutputBase) {
    if (Test-Path $outputBase) {
        Remove-Item $outputBase -Recurse -Force
    }
}

if (Test-Path $mdRoot) {
    Remove-Item $mdRoot -Recurse -Force
}

if (Test-Path $manifestPath) {
    Remove-Item $manifestPath -Force
}

New-Item -ItemType Directory -Force -Path $mdRoot | Out-Null
New-Item -ItemType Directory -Force -Path $manifestRoot | Out-Null

$stopwords = @(
    "그러니까", "그런데", "그래서", "이렇게", "저렇게", "그렇게",
    "있어요", "합니다", "하는", "되는", "하는데", "그거", "그게",
    "이거", "저거", "여기", "거예요", "정도", "부분", "조건", "상태",
    "얘기", "기준", "의미", "경우", "지금", "계속", "다시", "먼저",
    "나중에", "이제", "정말", "조금", "많이", "항상", "보면", "같은",
    "통해", "대한", "그냥", "본인", "자기", "하나", "둘", "셋", "이런",
    "저런", "우리", "여러분", "때문에", "가지고", "있다", "같다", "된다",
    "한다", "해서", "하면", "하면은", "또한", "그렇죠", "한다고", "하였다",
    "하는거", "하는것", "이것", "저것", "거죠", "수생", "목생", "생극", "제화",
    "강의", "파일", "정리", "총론", "회원전용", "코스", "기본", "다이제스트"
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

function Get-TitleHints {
    param([string]$Title)

    $tokens = [System.Collections.Generic.List[string]]::new()
    foreach ($match in [regex]::Matches($Title, "[가-힣A-Za-z]{2,}")) {
        $word = $match.Value.Trim()
        if ($word.Length -lt 2) {
            continue
        }
        if ($stopwords -contains $word) {
            continue
        }
        $tokens.Add($word)
    }
    return $tokens
}

function Get-TopKeywords {
    param(
        [string]$Text,
        $DomainTerms,
        [int]$Limit = 16
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

function Normalize-Keywords {
    param(
        $TitleHints,
        $Keywords,
        [int]$Limit = 10
    )

    $ordered = [System.Collections.Generic.List[string]]::new()
    foreach ($word in @($TitleHints + $Keywords)) {
        if ([string]::IsNullOrWhiteSpace($word)) {
            continue
        }
        $ordered.Add($word.Trim())
    }

    $deduped = [System.Collections.Generic.List[string]]::new()
    foreach ($candidate in $ordered) {
        if ($deduped -contains $candidate) {
            continue
        }

        $isShortSubword = $false
        foreach ($existing in $deduped) {
            if ($existing.Contains($candidate) -and $existing.Length -ge ($candidate.Length + 1) -and $candidate.Length -le 2) {
                $isShortSubword = $true
                break
            }
        }
        if ($isShortSubword) {
            continue
        }

        $deduped.Add($candidate)
        if ($deduped.Count -ge $Limit) {
            break
        }
    }

    return $deduped
}

function Get-PickSentences {
    param(
        $Sentences,
        $Keywords,
        [int]$Limit = 2
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

    return "${Concept}은 이 파일에서 반복적으로 연결되는 핵심 개념이다."
}

function Add-Particle {
    param(
        [string]$Text,
        [string]$Pair
    )

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return $Text
    }

    $parts = $Pair -split "/"
    if ($parts.Count -ne 2) {
        throw "Particle pair must use 'first/second' format."
    }

    $trimmed = $Text.Trim()
    $lastChar = [int][char]$trimmed[$trimmed.Length - 1]
    $hasBatchim = $false
    if ($lastChar -ge 0xAC00 -and $lastChar -le 0xD7A3) {
        $hasBatchim = ((($lastChar - 0xAC00) % 28) -ne 0)
    }

    $suffix = if ($hasBatchim) { $parts[0] } else { $parts[1] }
    return "${Text}${suffix}"
}

function Get-ThemeLead {
    param(
        $Group,
        [string]$Title
    )

    $first = $Group[0]
    $second = if ($Group.Count -ge 2) { $Group[1] } else { "" }
    if ([string]::IsNullOrWhiteSpace($second)) {
        return "이 파일은 $(Add-Particle $first '을/를') 중심으로 개념의 작동 방식과 적용 장면을 반복해서 설명한다."
    }
    return "이 파일은 $(Add-Particle $first '을/를') 출발점으로 $(Add-Particle $second '과/와') 연결되는 구조와 판단 흐름을 중심으로 전개된다."
}

function Get-QuestionBlocks {
    param(
        [string]$Title,
        $Concepts,
        $Sentences
    )

    $c1 = $Concepts[0]
    $c2 = $Concepts[1]
    $c3 = $Concepts[2]
    $c4 = $Concepts[3]

    return @(
        [pscustomobject]@{
            Question = "이 강의에서 가장 먼저 확인해야 할 판단축은 무엇인가?"
            Answer = "$(Add-Particle $c1 '을/를') 먼저 잡아야 한다. 대표 문장: $(Get-ConceptSentence $c1 $Sentences)"
        },
        [pscustomobject]@{
            Question = "$(Add-Particle $c1 '과/와') $(Add-Particle $c2 '이/가') 어떤 순서로 연결되는지 설명하라."
            Answer = "$(Add-Particle $c1 '과/와') $(Add-Particle $c2 '은/는') 분리해서 외우기보다 연결 구조로 읽어야 한다. 대표 문장: $(Get-ConceptSentence $c1 $Sentences)"
        },
        [pscustomobject]@{
            Question = "제목에 드러난 주제가 본문에서 어떤 방식으로 전개되는지 설명하라."
            Answer = "'$Title'은 ${c1}, ${c2}, $(Add-Particle $c3 '을/를') 통해 실제 판단 구조로 풀린다. 대표 문장: $(Get-ConceptSentence $c2 $Sentences)"
        },
        [pscustomobject]@{
            Question = "실전 해석에서 헷갈리기 쉬운 개념 한 쌍을 고르고 차이를 설명하라."
            Answer = "$(Add-Particle $c2 '과/와') $(Add-Particle $c3 '은/는') 함께 등장해도 같은 기능으로 보면 안 된다. 대표 문장: $(Get-ConceptSentence $c3 $Sentences)"
        },
        [pscustomobject]@{
            Question = "이 파일을 인접 강의와 구분할 때 반드시 기억해야 할 포인트는 무엇인가?"
            Answer = "이 파일의 구분점은 $(Add-Particle $c1 '과/와') $(Add-Particle $c4 '을/를') 묶어 읽는 방식에 있다. 대표 문장: $(Get-ConceptSentence $c4 $Sentences)"
        }
    )
}

function Get-ExamPoints {
    param(
        [string]$Title,
        $Concepts
    )

    $c1 = $Concepts[0]
    $c2 = $Concepts[1]
    $c3 = $Concepts[2]
    $c4 = $Concepts[3]

    return @(
        "$(Add-Particle $c1 '을/를') 출발점으로 놓고 ${c2}, ${c3} 순서로 연결해 볼 것.",
        "'$Title' 문맥에서는 $(Add-Particle $c1 '을/를') 단독 개념이 아니라 $(Add-Particle $c2 '과/와')의 관계로 읽을 것.",
        "$(Add-Particle $c3 '이/가') 등장할 때 $(Add-Particle $c4 '과/와') 섞어 외우지 말고 구분 포인트를 같이 정리할 것.",
        "인접 파일과 제목이 비슷해 보여도 이 파일의 중심축은 $(Add-Particle $c1 '과/와') $(Add-Particle $c2 '이라는/라는') 점을 기억할 것."
    )
}

function Get-CautionLines {
    param(
        [string]$Title,
        $Concepts
    )

    $c1 = $Concepts[0]
    $c2 = $Concepts[1]
    $c3 = $Concepts[2]

    return @(
        "$(Add-Particle $c1 '을/를') 단순 정의로만 외우면 실제 적용에서 틀리기 쉽다.",
        "$(Add-Particle $c2 '과/와') $(Add-Particle $c3 '은/는') 함께 나오더라도 같은 기능으로 뭉뚱그리지 말 것.",
        "원문 문장을 그대로 암기하기보다 '$Title'에서 ${c1} -> ${c2} 흐름이 어떻게 반복되는지 다시 정리할 것."
    )
}

function Build-StudyPack {
    param(
        [string]$FileName,
        [string]$Text
    )

    $title = Get-CleanTitle $FileName
    $agentLabel = Get-AgentLabel $AgentName
    $sentences = Split-Sentences $Text
    $titleHints = @(Get-TitleHints $title)
    $keywords = @(Get-TopKeywords $Text $domainTerms 16)
    $concepts = @(Normalize-Keywords $titleHints $keywords 10)

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

    $themeGroups = @()
    for ($i = 0; $i -lt [Math]::Min($concepts.Count, 8); $i += 2) {
        $group = @($concepts[$i])
        if ($i + 1 -lt $concepts.Count) {
            $group += $concepts[$i + 1]
        }
        $themeGroups += ,$group
    }
    if ($themeGroups.Count -eq 0) {
        $themeGroups = @(@("사주", "구조"))
    }

    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.Add("# $title 통합 학습 패키지 ($agentLabel)")
    $lines.Add("")
    $lines.Add("## 핵심 주제별로 나눠서 정리")
    $lines.Add("")

    $themeIndex = 1
    foreach ($group in $themeGroups) {
        $focus = if ($group.Count -ge 2) { Join-ConceptPair $group[0] $group[1] } else { $group[0] }
        $lines.Add("### 주제 ${themeIndex}: ${focus} 중심으로 정리한다")
        $lines.Add("- $(Get-ThemeLead $group $title)")
        foreach ($sent in (Get-PickSentences $sentences $group 2)) {
            $lines.Add("- $sent")
        }
        $lines.Add("")
        $themeIndex += 1
    }

    $lines.Add("## 핵심 개념 맵")
    foreach ($concept in ($concepts | Select-Object -First 6)) {
        $peer = if ($concept -eq $concepts[0]) { $concepts[1] } else { $concepts[0] }
        $lines.Add("- ${concept}: $(Add-Particle $concept '은/는') 이 파일에서 $(Add-Particle $peer '과/와') 연결되며, $(Get-ConceptSentence $concept $sentences)")
    }
    $lines.Add("")

    $lines.Add("## 예상 시험문제")
    $lines.Add("")
    $questionIndex = 1
    foreach ($block in (Get-QuestionBlocks $title $concepts $sentences)) {
        $lines.Add("### 문제 $questionIndex")
        $lines.Add("1. 예상 문제: $($block.Question)")
        $lines.Add("2. 정답 및 해설: $($block.Answer)")
        $lines.Add("")
        $questionIndex += 1
    }

    $lines.Add("## 시험 포인트와 실전 주의사항")
    $lines.Add("")
    $lines.Add("### 시험 포인트")
    foreach ($point in (Get-ExamPoints $title $concepts)) {
        $lines.Add("- $point")
    }
    $lines.Add("")
    $lines.Add("### 실전 주의사항")
    foreach ($caution in (Get-CautionLines $title $concepts)) {
        $lines.Add("- $caution")
    }
    $lines.Add("")

    $lines.Add("## 꼭 공부해야 할 내용")
    $lines.Add("")
    $lines.Add("### 핵심 키워드와 정의")
    foreach ($concept in ($concepts | Select-Object -First 4)) {
        $lines.Add("- ${concept}: $(Get-ConceptSentence $concept $sentences)")
    }
    $lines.Add("")
    $lines.Add("### 단계별 이해")
    $lines.Add("1. 먼저 '$($concepts[0])'을 기준으로 이 파일의 출발 판단을 한 줄로 정리한다.")
    $lines.Add("2. 다음으로 $(Add-Particle $($concepts[1]) '과/와') $(Add-Particle $($concepts[2]) '이/가') 어떻게 연결되는지 원문 문장으로 확인한다.")
    $lines.Add("3. 반복된 설명이 구조 설명인지 예시 설명인지 나눠 메모한다.")
    $lines.Add("4. 마지막으로 이 파일을 인접 강의와 구분하는 표현을 별도 표시해 복습한다.")

    return [pscustomobject]@{
        Title = $title
        Markdown = ($lines -join "`r`n") + "`r`n"
        Concepts = @($concepts | Select-Object -First 6)
        TitleHints = @($titleHints | Select-Object -First 6)
        ThemeFocuses = @(
            foreach ($group in $themeGroups) {
                if ($group.Count -ge 2) { Join-ConceptPair $group[0] $group[1] } else { $group[0] }
            }
        )
    }
}

$files = Get-ChildItem $resolvedInputRoot -Filter "*.script.txt" | Sort-Object Name
foreach ($file in $files) {
    $result = Build-StudyPack $file.Name (Get-Content $file.FullName -Raw -Encoding utf8)
    $destPath = Join-Path $mdRoot (([System.IO.Path]::GetFileNameWithoutExtension($file.Name)) + ".md")
    Set-Content -Path $destPath -Value $result.Markdown -Encoding utf8

    $manifestRow = [ordered]@{
        source_script = $file.FullName.Substring($repoRoot.Path.Length + 1).Replace("\", "/")
        draft_md = $destPath.Substring($repoRoot.Path.Length + 1).Replace("\", "/")
        course = $courseName
        title = $result.Title
        title_hints = $result.TitleHints
        concepts = $result.Concepts
        theme_focuses = $result.ThemeFocuses
        workflow = "draft-then-direct-rewrite"
        note = "자동 생성 md는 초안이다. 최종본은 GPT-5.4 direct session에서 파일별 재작성 후 확정한다."
    }
    Add-Content -Path $manifestPath -Value (($manifestRow | ConvertTo-Json -Compress)) -Encoding utf8
}

Write-Output ("RUN_TIMESTAMP={0}" -f $RunTimestamp)
Write-Output ("OUTPUT_BASE={0}" -f $outputBase)
Write-Output ("GENERATED_MD={0}" -f $files.Count)
Write-Output ("REWRITE_MANIFEST={0}" -f $manifestPath)

