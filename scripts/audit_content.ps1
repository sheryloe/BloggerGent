param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
  [string]$HtmlDir = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'storage/html'),
  [string]$OutputDir = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'storage/reports')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-PsqlLines {
  param([string]$Sql)

  $lines = & docker exec bloggent-postgres psql -U bloggent -d bloggent -At -F '|' -c $Sql
  if ($LASTEXITCODE -ne 0) {
    throw "psql query failed: $Sql"
  }
  return @($lines | Where-Object { $_ -and $_.Trim() })
}

function Get-ArticleProfileMap {
  $map = @{}
  $lines = Invoke-PsqlLines "select a.slug, b.profile_key from articles a join blogs b on b.id = a.blog_id;"
  foreach ($line in $lines) {
    $parts = $line -split '\|', 2
    if ($parts.Count -eq 2) {
      $map[$parts[0]] = $parts[1]
    }
  }
  return $map
}

function Get-CloudflareHits {
  $patterns = @('cloudflare', 'worker', 'workers', 'r2', 'cdn')
  $sql = @"
select 'articles' as source, a.slug as key, a.title as title
from articles a
where lower(a.slug) like any (array['%cloudflare%','%worker%','%workers%','%r2%','%cdn%'])
   or lower(a.title) like any (array['%cloudflare%','%worker%','%workers%','%r2%','%cdn%'])
union all
select 'topics' as source, cast(t.id as text) as key, t.keyword as title
from topics t
where lower(t.keyword) like any (array['%cloudflare%','%worker%','%workers%','%r2%','%cdn%'])
union all
select 'jobs' as source, cast(j.id as text) as key, j.keyword_snapshot as title
from jobs j
where lower(j.keyword_snapshot) like any (array['%cloudflare%','%worker%','%workers%','%r2%','%cdn%'])
order by source, key;
"@
  $lines = Invoke-PsqlLines $sql
  $hits = foreach ($line in $lines) {
    $parts = $line -split '\|', 3
    if ($parts.Count -eq 3) {
      [pscustomobject]@{
        source = $parts[0]
        key = $parts[1]
        title = $parts[2]
      }
    }
  }
  return @($hits)
}

function Get-ClusterKey {
  param([string]$Slug)

  $stopWords = @(
    'guide','tips','tip','transport','transit','booking','tickets','ticket','schedule','viewing','food','local','restaurants','restaurant',
    'accommodation','lodging','recommendations','recommendation','early','summer','spring','night','events','timing','best','new','modern',
    'revisited','review','analysis','explained','true','story','facts','theories','theory','history','historical','documentary','practical',
    'first','time','visitors','visitor','cultural','culture','festival','festivals','route','routes','travel','tour','touring'
  )

  $tokens = $Slug -split '-'
  $tokens = $tokens | Where-Object { $_ -notmatch '^(19|20)\d{2}$' -and $_ -notmatch '^\d{8,}$' }
  $core = New-Object System.Collections.Generic.List[string]

  foreach ($token in $tokens) {
    if ($core.Count -ge 4) { break }
    if ($stopWords -contains $token) {
      if ($core.Count -ge 2) { break }
      continue
    }
    $core.Add($token)
  }

  if ($core.Count -lt 2) {
    $fallback = $tokens | Select-Object -First ([Math]::Min(4, $tokens.Count))
    return ($fallback -join '-')
  }

  return ($core -join '-')
}

function Resolve-Profile {
  param(
    [string]$Slug,
    [hashtable]$ArticleProfileMap
  )

  if ($ArticleProfileMap.ContainsKey($Slug)) {
    return $ArticleProfileMap[$Slug]
  }

  if ($Slug -match 'mystery|witch|dyatlov|dahlia|somerton|roanoke|celeste|pharaoh|cooper|voynich|dybbuk|bermuda|molasses|woolpit|franklin|flannan|eilean|beale|oak-island|el-dorado|ningen|hinterkaifeck|sodder|hope-diamond|amber-room|axeman|dancing-plague|princes-in-the-tower|lost-city-of-z|mary-celeste|salem') {
    return 'world_mystery'
  }

  return 'korea_travel'
}

function Get-ContentRows {
  param(
    [string]$HtmlDir,
    [hashtable]$ArticleProfileMap
  )

  $files = Get-ChildItem -Path $HtmlDir -File | Where-Object { $_.Name -ne '.gitkeep' }
  $rows = foreach ($file in $files) {
    $slug = [System.IO.Path]::GetFileNameWithoutExtension($file.Name)
    $content = Get-Content -Raw $file.FullName
    $profile = Resolve-Profile -Slug $slug -ArticleProfileMap $ArticleProfileMap

    [pscustomobject]@{
      slug = $slug
      profile = $profile
      in_database = $ArticleProfileMap.ContainsKey($slug)
      cluster = Get-ClusterKey -Slug $slug
      length = $content.Length
      img_count = ([regex]::Matches($content, '<img\b')).Count
      api_assets = ([regex]::Matches($content, 'https://api\.dongriarchive\.com/assets')).Count
      has_transform = [bool]($content -match '/cdn-cgi/image')
      has_placeholder_link = [bool]($content -match 'href=["'']#')
      file_path = $file.FullName
    }
  }

  return @($rows)
}

function Get-ProfileSummary {
  param([object[]]$Rows)

  return @(
    $Rows | Group-Object profile | Sort-Object Name | ForEach-Object {
      $group = $_.Group
      [pscustomobject]@{
        profile = $_.Name
        files = @($group).Count
        missing_transform = @($group | Where-Object { -not $_.has_transform }).Count
        placeholder_links = @($group | Where-Object { $_.has_placeholder_link }).Count
        api_asset_files = @($group | Where-Object { $_.api_assets -gt 0 }).Count
        short_under_12000 = @($group | Where-Object { $_.length -lt 12000 }).Count
      }
    }
  )
}

function Get-DuplicateClusters {
  param(
    [object[]]$Rows,
    [string]$Profile
  )

  return @(
    $Rows |
      Where-Object { $_.profile -eq $Profile } |
      Group-Object cluster |
      Where-Object { $_.Count -gt 1 } |
      Sort-Object -Property @{ Expression = 'Count'; Descending = $true }, @{ Expression = 'Name'; Descending = $false } |
      Select-Object -First 12 |
      ForEach-Object {
        [pscustomobject]@{
          cluster = $_.Name
          count = $_.Count
          slugs = @($_.Group.slug | Sort-Object)
        }
      }
  )
}

function Get-PriorityCandidates {
  param(
    [object[]]$Rows,
    [string]$Profile,
    [int]$Limit = 12
  )

  return @(
    $Rows |
      Where-Object { $_.profile -eq $Profile } |
      Sort-Object @{ Expression = { if ($_.has_placeholder_link) { 0 } else { 1 } } },
                  @{ Expression = { if ($_.has_transform) { 1 } else { 0 } } },
                  length |
      Select-Object -First $Limit
  )
}

function Get-OrphanSnapshots {
  param(
    [object[]]$Rows,
    [int]$Limit = 20
  )

  return @(
    $Rows |
      Where-Object { -not $_.in_database } |
      Sort-Object length |
      Select-Object -First $Limit slug,profile,length,has_transform,has_placeholder_link,file_path
  )
}

function ConvertTo-MarkdownTable {
  param([object[]]$Rows)

  if (-not $Rows -or $Rows.Count -eq 0) {
    return @('없음')
  }

  $properties = $Rows[0].psobject.Properties.Name
  $header = '| ' + (($properties | ForEach-Object { $_ }) -join ' | ') + ' |'
  $separator = '| ' + (($properties | ForEach-Object { '---' }) -join ' | ') + ' |'
  $body = foreach ($row in $Rows) {
    $cells = foreach ($property in $properties) {
      $value = $row.$property
      if ($value -is [System.Array]) {
        ($value -join '<br>')
      } else {
        "$value"
      }
    }
    '| ' + ($cells -join ' | ') + ' |'
  }

  return @($header, $separator) + $body
}

function Add-StringLines {
  param(
    [System.Collections.Generic.List[string]]$Target,
    [object[]]$Lines
  )

  foreach ($line in $Lines) {
    $Target.Add([string]$line) | Out-Null
  }
}

function Write-Report {
  param(
    [object[]]$Rows,
    [object[]]$ProfileSummary,
    [object[]]$TravelClusters,
    [object[]]$MysteryClusters,
    [object[]]$TravelCandidates,
    [object[]]$MysteryCandidates,
    [object[]]$OrphanSnapshots,
    [object[]]$CloudflareHits,
    [string]$OutputDir
  )

  New-Item -ItemType Directory -Force $OutputDir | Out-Null
  $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
  $generatedAt = Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'

  $total = @($Rows).Count
  $missingTransform = @($Rows | Where-Object { -not $_.has_transform }).Count
  $placeholderLinks = @($Rows | Where-Object { $_.has_placeholder_link }).Count
  $apiAssetFiles = @($Rows | Where-Object { $_.api_assets -gt 0 }).Count
  $shortFiles = @($Rows | Where-Object { $_.length -lt 12000 }).Count
  $orphanFiles = @($Rows | Where-Object { -not $_.in_database }).Count

  $reportLines = New-Object System.Collections.Generic.List[string]
  $reportLines.Add("# 콘텐츠 감사 리포트 ($generatedAt)")
  $reportLines.Add('')
  $reportLines.Add('## 전체 요약')
  $reportLines.Add("- 전체 HTML 파일: $total")
  $reportLines.Add('- `/cdn-cgi/image` 미적용 파일: ' + $missingTransform)
  $reportLines.Add('- placeholder 링크(`href="#"`) 포함 파일: ' + $placeholderLinks)
  $reportLines.Add('- `https://api.dongriarchive.com/assets` 원본 URL 사용 파일: ' + $apiAssetFiles)
  $reportLines.Add("- 길이 12,000자 미만 파일: $shortFiles")
  $reportLines.Add("- DB에 없는 레거시 HTML 스냅샷: $orphanFiles")
  $reportLines.Add('')
  $reportLines.Add('## 프로필별 요약')
  Add-StringLines -Target $reportLines -Lines (ConvertTo-MarkdownTable -Rows $ProfileSummary)
  $reportLines.Add('')
  $reportLines.Add('## DB에 없는 레거시 HTML 스냅샷')
  Add-StringLines -Target $reportLines -Lines (ConvertTo-MarkdownTable -Rows $OrphanSnapshots)
  $reportLines.Add('')
  $reportLines.Add('## 한국 여행 중복 군집')
  Add-StringLines -Target $reportLines -Lines (ConvertTo-MarkdownTable -Rows $TravelClusters)
  $reportLines.Add('')
  $reportLines.Add('## 미스테리 중복 군집')
  Add-StringLines -Target $reportLines -Lines (ConvertTo-MarkdownTable -Rows $MysteryClusters)
  $reportLines.Add('')
  $reportLines.Add('## 한국 여행 우선 수정 대상')
  Add-StringLines -Target $reportLines -Lines (ConvertTo-MarkdownTable -Rows ($TravelCandidates | Select-Object slug,length,img_count,api_assets,has_transform,has_placeholder_link))
  $reportLines.Add('')
  $reportLines.Add('## 미스테리 우선 수정 대상')
  Add-StringLines -Target $reportLines -Lines (ConvertTo-MarkdownTable -Rows ($MysteryCandidates | Select-Object slug,length,img_count,api_assets,has_transform,has_placeholder_link))
  $reportLines.Add('')
  $reportLines.Add('## Cloudflare 관련 탐지')
  $cloudflareRows = New-Object System.Collections.Generic.List[object]
  if ($null -ne $CloudflareHits) {
    foreach ($hit in $CloudflareHits) {
      $cloudflareRows.Add($hit) | Out-Null
    }
  }
  if ($cloudflareRows.Count -eq 0) {
    $reportLines.Add('- 현재 저장소의 `articles`, `topics`, `jobs` 테이블에서는 Cloudflare/R2/CDN/Worker 키워드 기반 글이 탐지되지 않았습니다.')
    $reportLines.Add('- 즉, 지금 저장소 기준으로는 별도 Cloudflare 글 원본이 없거나 다른 프로젝트/외부 초안에 있을 가능성이 높습니다.')
  } else {
    Add-StringLines -Target $reportLines -Lines (ConvertTo-MarkdownTable -Rows $cloudflareRows.ToArray())
  }
  $reportLines.Add('')
  $reportLines.Add('## 즉시 작업 권고')
  $reportLines.Add('- 한국 여행: 중복 군집이 큰 `seoul-lotus-lantern`, `royal-palaces-of-seoul`, `hwacheon-sancheoneo-ice`, `jinhae-gunhangje`, `insadong-street`, `busan-sea`부터 통폐합 기준을 잡습니다.')
  $reportLines.Add('- 한국 여행: `seoul-night-market-itinerary-with-transit-tips`, `jeonju-hanok-village-one-day-route-for-foreigners`, `busan-spring-festival-schedule-and-local-tips`는 placeholder 링크가 있어 우선 수리 대상입니다.')
  $reportLines.Add('- 미스테리: `dyatlov-pass`, `black-dahlia`, `eilean-mor`, `princes-in-the-tower` 계열은 내용 중복과 길이 부족이 같이 보여 재작성 우선순위가 높습니다.')
  $reportLines.Add('- 이미지: 현재는 대부분 원본 `api.dongriarchive.com/assets`를 직접 쓰고 있어, HTML 렌더 단계에서 `/cdn-cgi/image` 변환 URL로 바꾸는 공통 처리 작업이 필요합니다.')

  $markdownPath = Join-Path $OutputDir "content-audit-$stamp.md"
  $jsonPath = Join-Path $OutputDir "content-audit-$stamp.json"

  Set-Content -Path $markdownPath -Value $reportLines -Encoding UTF8
  $payload = [pscustomobject]@{
    generated_at = $generatedAt
    totals = [pscustomobject]@{
      total = $total
      missing_transform = $missingTransform
      placeholder_links = $placeholderLinks
      api_asset_files = $apiAssetFiles
      short_under_12000 = $shortFiles
      orphan_html_files = $orphanFiles
    }
    profile_summary = $ProfileSummary
    orphan_snapshots = $OrphanSnapshots
    travel_clusters = $TravelClusters
    mystery_clusters = $MysteryClusters
    travel_candidates = $TravelCandidates
    mystery_candidates = $MysteryCandidates
    cloudflare_hits = $CloudflareHits
  }
  $payload | ConvertTo-Json -Depth 6 | Set-Content -Path $jsonPath -Encoding UTF8

  [pscustomobject]@{
    markdown = $markdownPath
    json = $jsonPath
  }
}

$articleProfileMap = Get-ArticleProfileMap
$rows = Get-ContentRows -HtmlDir $HtmlDir -ArticleProfileMap $articleProfileMap
$profileSummary = Get-ProfileSummary -Rows $rows
$travelClusters = Get-DuplicateClusters -Rows $rows -Profile 'korea_travel'
$mysteryClusters = Get-DuplicateClusters -Rows $rows -Profile 'world_mystery'
$travelCandidates = Get-PriorityCandidates -Rows $rows -Profile 'korea_travel'
$mysteryCandidates = Get-PriorityCandidates -Rows $rows -Profile 'world_mystery'
$orphanSnapshots = Get-OrphanSnapshots -Rows $rows
$cloudflareHits = Get-CloudflareHits
$result = Write-Report -Rows $rows -ProfileSummary $profileSummary -TravelClusters $travelClusters -MysteryClusters $mysteryClusters -TravelCandidates $travelCandidates -MysteryCandidates $mysteryCandidates -OrphanSnapshots $orphanSnapshots -CloudflareHits $cloudflareHits -OutputDir $OutputDir

Write-Output "MARKDOWN=$($result.markdown)"
Write-Output "JSON=$($result.json)"
