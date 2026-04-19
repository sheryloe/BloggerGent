# BloggerGent Scripts Layout

Repository scripts are grouped by operating scope. Generated reports, dumps, and logs must not be written to repo-local `storage`.

Runtime roots:

```powershell
$RuntimeRoot = "D:\Donggri_Runtime\BloggerGent"
$StorageRoot = "D:\Donggri_Runtime\BloggerGent\storage"
$DbSnapshotRoot = "D:\Donggri_Runtime\BloggerGent\db\snapshots"
```

Directory contract:

```text
scripts\common       shared helpers
scripts\db           database snapshots, cleanup, rebuild jobs
scripts\lighthouse   required Lighthouse audit and DB score sync
scripts\travel       Travel-only jobs, blog_id 34/36/37 only
scripts\mystery      Mystery-only jobs
scripts\cloudflare   Cloudflare channel jobs
scripts\planner      monthly planner jobs
scripts\maintenance  cleanup, env sync, repo/runtime maintenance
```

Required commands:

```powershell
Set-Location D:\Donggri_Platform\BloggerGent

python .\scripts\lighthouse\sync_lighthouse_scores.py --published-only --form-factor mobile
python .\scripts\lighthouse\sync_cloudflare_lighthouse_scores.py --form-factor mobile --only-missing

powershell -ExecutionPolicy Bypass -File .\scripts\db\run_rebuild_analysis_db_from_live.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\db\run_db_cleanup_20260410.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\maintenance\sync_settings_env.ps1 -OutPath .\env\runtime.settings.env
```

Forbidden defaults:

```text
repo-local generated report root
repo-local generated backup root
legacy Travel log root outside runtime travel
```

Use these instead:

```text
D:\Donggri_Runtime\BloggerGent\storage\_common\analysis
D:\Donggri_Runtime\BloggerGent\db\snapshots
D:\Donggri_Runtime\BloggerGent\storage\travel
```
