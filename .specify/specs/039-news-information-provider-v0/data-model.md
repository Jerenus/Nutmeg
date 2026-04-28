# Data Model: News Information Provider v0

## InformationItem

- `item_id`: stable id from source or generated hash.
- `source_name`: source label.
- `source_type`: `json`, `rss`, `atom`, or `unknown`.
- `title`: item headline/title.
- `summary`: short description.
- `url`: source URL when available.
- `published_at`: publication timestamp when available.
- `retrieved_at`: local retrieval/parse timestamp.
- `reliability`: `official`, `credible`, `rumor`, or `unverified`.
- `fixture_ids`: fixture ids directly tagged by source.
- `teams`: team names tagged or inferred from source metadata.
- `tags`: context tags such as `lineup`, `injury`, `fixture_status`, `team_news`.
- `metadata`: provider-specific fields preserved for audit/debug.

## InformationSourceHealth

- `source_name`
- `source_type`
- `status`: `complete`, `partial`, or `unavailable`
- `item_count`
- `warnings`
- `retrieved_at`

## FixtureInformationDigest

- `fixture_id`
- `status`: `complete`, `partial`, or `unavailable`
- `summary`
- `items`
- `source_count`
- `latest_published_at`
- `warnings`
- `generated_at`

Validation:

- Duplicate URL or duplicate normalized title/source collapses to one item.
- Rumor/unverified items remain visible but labeled.
- Missing source files produce unavailable digest with empty items.
