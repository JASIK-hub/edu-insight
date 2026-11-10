# Analytics contract and integration

This module accepts an assessment DataFrame and optional catalog DataFrames and returns JSON-compatible dictionaries.
`assessments` has one row per assessment attempt. The v1 CSV columns
`student_id`, `topic`, `textbook`, `score`, and `max_score` are sufficient.
Alternatively, callers may use `topic_id` and `textbook_id`. Optional
`assessment_id`, `grade`, and `subject` add grouping detail. Catalogs may be
omitted and will be inferred from observations. `topics` requires unique
`topic_id` (or `topic`) and may include
`curriculum_importance` on a 0–1 scale (default 0.5). `textbooks` requires
unique `textbook_id` (or `textbook`). Optional assessment columns `baseline_score` and
`baseline_max_score` must be supplied together to compute paired gains.

## Formulas

- Valid normalized score = `score / max_score`, for finite scores with
  `max_score > 0` and `0 <= score <= max_score`. Invalid attempts remain in
  total assessment counts and are excluded from score statistics.
- Average mastery and textbook average score are arithmetic means of valid
  assessment normalized scores. This weights attempts equally, including
  repeated attempts from one student. Median uses the same valid attempts.
- The frozen v1 API in `docs/data-dictionary.md` defines `mastery` as
  `sum(score) / sum(max_score)`, which weights attempts by max score. This
  engine's `average_normalized_mastery` and `average_normalized_score` are
  equal-weight means of per-attempt normalized scores. Adapters to the v1
  contract must use its weighted ratio for `mastery` fields.
- Student count is the number of distinct students with valid attempts in
  that group. Assessment count in grouped results is valid attempts.
- Error rate is the fraction of valid attempts with normalized score below
  0.5. Distribution bins are low `[0, 0.5)`, developing `[0.5, 0.8)`, and
  mastered `[0.8, 1]`. Mastery category uses the group mean and these cutoffs.
- Priority indicator = `0.6 * (1 - average_mastery) + 0.25 * error_rate +
  0.15 * curriculum_importance`; it is null without valid scores. Difficulty
  requires at least 10 valid attempts, mean below 0.6, error rate at least
  0.4, and importance at least 0.5 by default. Critical topics have at least
  10 valid attempts and mean below 0.5.
- Assessment coverage is the fraction of supplied catalog topics referenced
  by any assessment attempt, regardless of score validity. An omitted or
  empty topic catalog produces null coverage; inferred catalogs are not
  treated as proof of complete curriculum coverage.
- Baseline adjusted mean gain is the mean of `normalized_score -
  normalized_baseline` over attempts with both valid values. It is a
  within-attempt descriptive change, not a causal estimate. Comparisons are
  grouped by grade, subject, topic, and textbook. All textbook differences
  are observational and do not establish textbook effectiveness.
- Unequal groups are flagged when, within the same grade, subject, and topic,
  the largest valid attempt count is at least twice the smallest. A group of
  fewer than 10 valid attempts is flagged as insufficient by default.

## Integration

The application data layer should load a consistent dataset snapshot into a
DataFrame and call `app.services.analytics_service.build_analytics_report(...)`
or `app.services.textbook_service.compare_textbooks(...)`. For example:

```python
report = build_analytics_report(assessments_df, topics_df, textbooks_df)
comparison = compare_textbooks(assessments_df, topics_df, textbooks_df)
```

The existing `backend/app` package and its frozen v1 response models are a
separate integration boundary. An adapter must map only supported fields to
those models, retaining the v1 weighted mastery ratio, dataset resolution,
and sorting rules. New rich fields require a separately approved API contract.
The services make no database, network, AI, or HTTP calls. Catalog IDs must
have the same dtype as assessment foreign keys; normalize them in the data
layer if needed. `subject` is optional in v1 and appears as null in rich
comparisons when absent.
