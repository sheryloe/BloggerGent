# BloggerGent Runtime Layout (Antigravity)

## Fixed paths
- Source code root: `D:\Donggri_Platform\BloggerGent`
- Runtime root: `D:\Donggri_Runtime\BloggerGent`
- Runtime data:
  - `D:\Donggri_Runtime\BloggerGent\app`
  - `D:\Donggri_Runtime\BloggerGent\backup`
  - `D:\Donggri_Runtime\BloggerGent\storage`
  - `D:\Donggri_Runtime\BloggerGent\db\snapshots`
  - `D:\Donggri_Runtime\BloggerGent\tools`
  - `D:\Donggri_Runtime\BloggerGent\env\runtime.settings.env`

## Operational contract
- Keep only reproducible source/config files in repo.
- Keep runtime artifacts, reports, caches, and one-off outputs in runtime root.
- Repo-local generated report folders must not stay in repo.
- Lighthouse reports must use `D:\Donggri_Runtime\BloggerGent\storage\_common\analysis\lighthouse`.
- Travel reports/logs must use `D:\Donggri_Runtime\BloggerGent\storage\travel`.
- SQL full dump snapshots must use `D:\Donggri_Runtime\BloggerGent\db\snapshots`.
- `env/runtime.settings.env` is an operational settings file and must not be deleted by one-off cleanup.
- Docker live mount source for `/app/storage` is `D:\Donggri_Runtime\BloggerGent\storage`.
- Do not use repo-local `./storage` as the live default mount.

## Recovery commands (PowerShell)
```powershell
Set-Location D:\Donggri_Platform\BloggerGent

# 1) Rebuild runtime.settings.env from DB settings
powershell -ExecutionPolicy Bypass -File scripts/maintenance/sync_settings_env.ps1 -OutPath env/runtime.settings.env

# 2) Runtime backup copy
New-Item -ItemType Directory -Force -Path D:\Donggri_Runtime\BloggerGent\env | Out-Null
Copy-Item -LiteralPath D:\Donggri_Platform\BloggerGent\env\runtime.settings.env -Destination D:\Donggri_Runtime\BloggerGent\env\runtime.settings.env -Force
```

## One-off cleanup rule
- Use `scripts/maintenance/cleanup_oneoff_artifacts.ps1` for one-off cleanup.
- `env` deletion requires explicit opt-in:
  - `-DeleteEnv -AllowEnvDelete`
- Without `-AllowEnvDelete`, env deletion is blocked and logged in `protected_skipped`.
