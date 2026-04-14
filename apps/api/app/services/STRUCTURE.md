# Services Structure

## Blog-Specific
- `blogger/`: Blogger channel domain services
- `cloudflare/`: Cloudflare channel domain services

## Cross-Channel (Category Folders)
- `content/`: article generation, prompting, HTML assembly, related posts, topic/training/editorial helpers
- `ops/`: analytics, metrics, scheduling/health, model usage/policy, operations dashboards
- `integrations/`: Google/Search/Sheets plus settings/secrets/storage/Telegram/integration helpers
- `platform/`: workspace/blog/platform orchestration and publishing flow

## Import Rules
- New code should import moved modules via:
  - `app.services.blogger.*`
  - `app.services.cloudflare.*`
  - `app.services.content.*`
  - `app.services.ops.*`
  - `app.services.integrations.*`
  - `app.services.platform.*`
- Legacy imports (`app.services.article_service`, `app.services.blogger_sync_service`, etc.) are kept by aliases in `app.services.__init__` for compatibility.
