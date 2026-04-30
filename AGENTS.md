# BloggerGent AGENT Rules

Respond pragmatically and structurally. Use concise Korean unless the user asks otherwise.

- Focus on executable decisions and concrete next steps.
- Prefer PowerShell examples for local operations.
- Do not output partial code when code is requested.
- Preserve unrelated user changes in the working tree.
- When unsure and the answer cannot be discovered safely, ask one direct question.

## Codex-Owned Pipeline Architecture (Critical)
- Codex owns travel operations end-to-end from topic selection through live validation and reporting.
- Do not route travel work through external orchestrator assumptions.
- Do not use Docker worker fallbacks for travel generation unless explicitly requested by the user.
- Travel generation, image prompt generation, validation, Blogger update, DB sync, audit, and reporting must be controlled by the BloggerGent/Codex workflow.

## Travel Log Path (Mandatory)
- Runtime travel logs, manifests, reports, and temporary command payloads belong under `D:\Donggri_Runtime\BloggerGent\storage\travel`.
- Repo-local generated reports are not canonical runtime storage.
- Temporary payload and command files must be deleted after execution unless explicitly preserved.

## Travel Publication Rules (Critical)
- Image domain: `https://api.dongriarchive.com`.
- Do not use `img.` domains for travel hero images.
- Image format: WebP only, Content-Type `image/webp`.
- Canonical image prefix: `assets/travel-blogger/`.
- Canonical hero asset category: `travel` or `culture` only.
- Editorial `food` is allowed, but hero asset paths currently resolve to `travel` unless policy changes explicitly.
- Minimum pure body text: 3000 visible non-space characters.
- Recommended body text: 3500+ visible non-space characters.
- Google Maps iframe is optional and must not be a hard fail condition.
- Success requires live URL validation, not only Blogger API success or DB row creation.

## Travel Pattern & Visual Rules (Strict)
- Travel patterns are exactly:
  1. `travel-01-hidden-path-route`
  2. `travel-02-cultural-insider`
  3. `travel-03-local-flavor-guide`
  4. `travel-04-seasonal-secret`
  5. `travel-05-smart-traveler-log`
- Pattern metadata must include `article_pattern_id`, `article_pattern_version`, `article_pattern_key`, and `article_pattern_version_key`.
- Travel sync articles must not inherit the source EN article pattern by default.
- Pattern selection is blog-specific even inside the same `travel_sync_group_key`.
- EN/ES/JA versions of the same topic may use different travel patterns to avoid repetitive structure and improve channel fit.
- Runtime selection must choose from the five travel patterns per blog using channel context, category, topic angle, and recent-pattern diversity.
- Runtime selection is deterministic random from `blog_id + travel_sync_group_key + editorial_category_key + topic/slug seed`.
- Same blog recent-pattern guard is strict: do not allow the next article to become a third consecutive identical travel pattern.
- JA travel article `slug` must be English ASCII kebab-case based on the source EN slug or English topic keywords.
- JA travel publication must preserve the Japanese visible title while forcing the Blogger permalink from the English slug seed; never leave `blog-post`, numeric-only, or Japanese-title-derived URL paths for new posts.
- Hero image result is always one single flattened final image.
- Hero image layout is `4 columns x 3 rows` visible editorial collage.
- Hero image must show exactly 12 distinct visible panels.
- Thin white gutters must be visible between panels.
- Do not generate 12 separate images.
- Do not generate one single hero shot without panel structure.
- No text, logos, or watermarks in generated images.
- Body-level `<h1>` is forbidden; the assembled article shell owns the only article `<h1>`.
- Travel body balance target: field information 45%, route/queue/reservation judgment 30%, atmosphere 15%, SEO/FAQ/internal links 10%.
- Duplicate sentences, repeated paragraphs, duplicated meta/excerpt/intro text, and repeated JA closing/template paragraphs are hard failures.
- Route-unrelated `river` / `川沿い` / `río` wording is a hard failure unless the actual route includes a water route.
- User-facing travel reports must omit `post_status`; DB rows are final live rows after publish validation.
- Reports must include SEO, GEO, Search Console CTR when present, title CTR heuristic score, and Lighthouse status/score when available.
- Lighthouse/web-vitals scores must come from Google PageSpeed/Lighthouse results or a Chrome DevTools plugin export. Do not invoke a local Lighthouse CLI from the travel pipeline, and do not block publish completion when this optional measurement is unavailable.

## Travel Editorial Categories
- `travel`: route flow, transit, timing, queue avoidance, nearby pairing.
- `culture`: event timing, venue context, ticketing, etiquette, crowd timing.
- `food`: order strategy, queue signals, budget, menu choice, nearby route pairing.

## Global Workflow Rule
Travel canonical sequence:
1. Topic generation.
2. DB plus live duplicate review.
3. Article generation.
4. Image prompt generation.
5. Image generation.
6. HTML assembly.
7. Blogger publish or same-post update.
8. Live URL validation.
9. DB completion only after live validation.
10. Heartbeat, report, audit log, and Telegram reporting.
