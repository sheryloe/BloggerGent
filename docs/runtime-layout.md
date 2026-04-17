# BloggerGent Runtime Layout (Antigravity 기준)

## 고정 경로
- 소스 코드: `D:\Donggri_Platform\BloggerGent`
- 런타임 루트: `D:\Donggri_Runtime\BloggerGent`
- 런타임 데이터:
  - `D:\Donggri_Runtime\BloggerGent\app`
  - `D:\Donggri_Runtime\BloggerGent\backup`
  - `D:\Donggri_Runtime\BloggerGent\storage`
  - `D:\Donggri_Runtime\BloggerGent\tools`
  - `D:\Donggri_Runtime\BloggerGent\tools\reports\repo-storage-reports`

## 운영 규칙
- 레포(`D:\Donggri_Platform\BloggerGent`)는 소스/설정만 유지한다.
- 실행 산출물, 캐시, 1회성 검증 파일은 runtime 경로에만 둔다.
- `storage/reports`는 레포에 상주하지 않고 runtime으로만 저장한다.
- 레포 루트에 아래 항목이 재생성되면 즉시 runtime으로 이동/정리한다:
  - `.playwright-cli`
  - `output`
  - `TEST`
  - `backup`
  - `apps/storage`
  - `storage/reports`

## 점검 명령 (PowerShell)
```powershell
Set-Location D:\Donggri_Platform\BloggerGent

$targets = @(
  '.playwright-cli',
  'output',
  'TEST',
  'backup',
  'apps/storage',
  'storage/reports'
)

foreach ($t in $targets) {
  if (Test-Path -LiteralPath (Join-Path $PWD $t)) {
    Write-Host "[FOUND] $t"
  }
}

git status --short
```

## 이관/정리 리포트
- `D:\Donggri_Runtime\BloggerGent\tools\reports\runtime-rehome-report-20260417.json`
- `D:\Donggri_Runtime\BloggerGent\tools\reports\oneoff-cleanup-preview-20260417.json`
