[Input]
- Current date: {current_date}
- Audience: {target_audience}
- Blog focus: {content_brief}

[Mission]
- Suggest high-interest Korean mystery story topics for Dongri Archive.
- Prioritize search-worthy, history-backed, evidence-rich mystery cases.

[Allowed 5 Patterns Only]
- case-timeline
- evidence-breakdown
- legend-context
- scene-investigation
- scp-dossier

[Rules]
- Avoid duplicate or near-duplicate topics.
- Avoid raw topic echo titles.
- Prefer cases with enough documentary material to support 3000+ Korean characters.

[Output]
Return JSON only:
{
  "topics": [
    {
      "keyword": "...",
      "reason": "...",
      "trend_score": 0
    }
  ]
}
