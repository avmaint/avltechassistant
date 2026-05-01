# Knowledge Base `SeeAlso` Feature Analysis

## Summary

The knowledge base data now includes a new `SeeAlso` attribute containing a comma-delimited list of related issue IDs.

The requested UI behavior is:

- add a new detail section titled `See Also`
- place it before the existing `Tags` field in the Knowledge Base issue detail view
- render the section as a unique list of clickable entries
- each entry shows:
  - related `IssueID`
  - related issue `Title`
- clicking an entry refreshes the page content with the related issue
- relationships must be treated as bidirectional for display purposes
  - if `KB123` lists `KB456`, then `KB456` should also display `KB123` even if its source row does not explicitly list it
- the displayed list must be unique

This feature primarily affects:

- knowledge base loading and response shaping in [backend/main.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/backend/main.py:84)
- knowledge base detail rendering in [frontend/script.js](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/script.js:2240)
- issue-to-issue navigation behavior in [frontend/script.js](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/script.js:1968)
- knowledge base requirements in [requirements.md](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/requirements.md:82)
- backend tests in [tests/run_tests.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/tests/run_tests.py:472)

## Current State

### Backend

The knowledge base loader in [backend/main.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/backend/main.py:84) currently:

- loads the `Issues` sheet
- trims column names
- normalizes `AppliesToAssetTag`
- drops rows with empty `IssueID`

The current search endpoint in [backend/main.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/backend/main.py:840) returns raw KB records with only minor cleanup. There is no existing:

- `SeeAlso` parsing
- issue-to-issue relationship normalization
- bidirectional relationship generation
- title-enriched related-issue payload

### Frontend

The Knowledge Base result/detail renderer is [frontend/script.js](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/script.js:2240).

Issue details are currently rendered as a simple ordered list of labeled fields:

- Category
- Subcategory
- Symptom
- Trigger Conditions
- Likely Cause
- Recovery Steps
- Applies to Asset Type
- Applies to Asset Tag
- Tags
- Notes

There is currently no `See Also` section.

The existing UI already supports one KB navigation path:

- clicking an `IssueID` in the Asset Details KB table switches to the KB tab
- populates the `Issue ID` search field
- runs `performKBSearch()`

See [frontend/script.js](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/script.js:1968).

That means the basic navigation pattern needed for `See Also` already exists.

### Tests

Current KB tests only validate:

- issue-id search
- tag search
- freeform search
- required result fields

See [tests/run_tests.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/tests/run_tests.py:472).

There is no test coverage for:

- `SeeAlso` field parsing
- related-issue enrichment with titles
- uniqueness
- synthetic reverse relationship generation

### Requirements

The current requirements for the Knowledge Base tab in [requirements.md](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/requirements.md:82) describe searchable fields and expandable issue details, but they do not mention:

- a `See Also` section
- related issue links
- ordering relative to `Tags`
- reverse-link generation

## Recommended Design

## Backend-Centric Enrichment

The cleanest design is to compute `See Also` relationships in the backend and return an already-enriched field per issue, rather than trying to derive reverse links in the browser.

Recommended returned shape per issue:

```json
{
  "IssueID": "KB123",
  "Title": "Primary issue",
  "SeeAlso": "KB456, KB789",
  "SeeAlsoResolved": [
    { "IssueID": "KB456", "Title": "Related title 1" },
    { "IssueID": "KB789", "Title": "Related title 2" }
  ]
}
```

This design is preferable because:

- relationship normalization happens once
- reverse-link generation is centralized
- uniqueness rules are easier to guarantee
- the frontend only renders the already-resolved list
- tests can validate one consistent API contract

## Relationship Rules

The backend should apply these rules when building `SeeAlsoResolved`:

1. Parse each issue’s raw `SeeAlso` value as a comma-delimited list.
2. Trim whitespace and normalize issue IDs case-insensitively.
3. Ignore blanks.
4. Ignore self-references.
5. Add explicit outgoing relationships from the source row.
6. Add implicit reverse relationships for display purposes.
   Example:
   - if `KB123 -> KB456` exists explicitly
   - then `KB456 -> KB123` must also appear in display output even if absent in raw data
7. Deduplicate the final list per issue.
8. Enrich each related issue with its title when the target issue exists.

## Handling Missing or Invalid Related Issue IDs

The workbook may contain `SeeAlso` references to IDs that do not exist in the sheet.

Recommended behavior:

- keep the relationship only if the referenced issue exists
- omit unknown IDs from `SeeAlsoResolved`
- optionally preserve the raw `SeeAlso` string for data inspection, but do not render broken clickable links

This avoids dead-end navigation in the UI.

## Ordering Recommendation

For consistent display, sort each issue’s resolved related list by:

1. `IssueID` case-insensitively

This is simple, deterministic, and easy to test.

## Required Backend Changes

### 1. Extend KB load-time normalization

Update [backend/main.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/backend/main.py:84) to normalize the new `SeeAlso` column.

Recommended additions during load:

- ensure `SeeAlso` exists and is treated as string
- create a lookup of:
  - normalized `IssueID` -> canonical row / display `IssueID`
  - normalized `IssueID` -> `Title`
- parse raw `SeeAlso` references into normalized ID sets

### 2. Build bidirectional relationship maps

Add a helper that builds a per-issue related-issue set:

- add each explicit relation
- also add the reverse relation to the target issue
- deduplicate via set semantics

This helper should be run:

- when KB data is loaded
- and again after `/data/reload`

### 3. Enrich KB search responses

Update [backend/main.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/backend/main.py:840) so `/knowledgebase/search` includes a resolved field such as:

- `SeeAlsoResolved`

Each item should include:

- `IssueID`
- `Title`

The existing raw `SeeAlso` column can also be returned if useful, but the frontend should rely on the resolved structure for display.

### 4. Preserve backward-compatible result behavior

All current search fields and sort behavior should remain intact. This feature is additive to the search result payload.

## Required Frontend Changes

### 1. Add `See Also` to the KB detail rendering order

Update the detail field construction in [frontend/script.js](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/script.js:2269) so `See Also` appears:

- after `Applies to Asset Tag`
- before `Tags`

This should be rendered as a dedicated list section rather than plain markdown text.

### 2. Render clickable related-issue entries

For each item in `SeeAlsoResolved`, render:

- the issue ID as clickable text
- the title alongside it

Recommended display format:

- `KB456 - Related issue title`

Each item should be an individual clickable row or inline link entry.

### 3. Reuse existing KB navigation behavior

Clicking a `See Also` entry should:

- switch or stay on the Knowledge Base tab
- clear other KB search fields as appropriate
- populate the `Issue ID` search field with the clicked issue ID
- run `performKBSearch()`

This matches the existing navigation path already used by Asset Details issue links in [frontend/script.js](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/script.js:1968).

### 4. Keep the displayed list unique

The frontend should ideally not need to deduplicate if the backend contract is correct, but it is still reasonable to defensively avoid duplicate DOM entries by keying on `IssueID`.

## Required Test Changes

New and modified tests are required.

### Backend Tests to Add

Add tests in [tests/run_tests.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/tests/run_tests.py:472):

1. `test_knowledgebase_search_returns_seealso_resolved`
   - search for a known issue with `SeeAlso`
   - verify `SeeAlsoResolved` exists and is a list
   - verify each entry contains:
     - `IssueID`
     - `Title`

2. `test_knowledgebase_seealso_reverse_link_generated`
   - for a known one-way source relationship, verify the related target issue includes the reverse link in `SeeAlsoResolved`

3. `test_knowledgebase_seealso_unique`
   - verify duplicate raw or derived relationships are collapsed to one display entry per issue

4. `test_knowledgebase_seealso_ignores_unknown_ids`
   - if fixture data supports it, verify nonexistent related IDs are not emitted as clickable resolved entries

### Existing Tests to Modify

1. Extend `test_knowledgebase_search_returns_required_fields`
   - continue requiring the current core fields
   - add validation for `SeeAlsoResolved` if present in the new contract

2. Keep existing KB search tests unchanged otherwise.
   They should continue to pass because the search payload remains backward-compatible.

### Manual Frontend Verification

Because there is no frontend automation in this repo, manual verification should include:

- a KB issue with explicit `SeeAlso` values renders a `See Also` section
- the section appears before `Tags`
- each entry shows issue ID and title
- clicking an entry reloads the KB view to the clicked issue
- reverse links appear even when only one side is declared in raw data
- duplicates do not appear

## Requirements Updates Needed

Update [requirements.md](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/requirements.md:82).

Recommended addition under the Knowledge Base issue-detail requirements:

> Each expanded knowledge base issue must display a `See Also` section before the `Tags` field when related issues exist. The section must list unique related issues using the issue ID and title. Each related issue entry must be clickable and, when clicked, must refresh the Knowledge Base tab to display that issue. Related-issue display must be bidirectional for UI purposes: if issue A references issue B in `SeeAlso`, then issue B must also display issue A in its `See Also` section even if the reverse relationship is not explicitly present in the source data.

## Risks and Decisions

### Decision: where reverse-link generation lives

Recommended:

- backend

Not recommended:

- frontend-only derivation

Reason:

- frontend-only derivation would require the browser to know about all issues, not just the current search result
- reverse-link correctness would become dependent on what subset happened to be returned by the current search

### Risk: search result subset vs global KB graph

Reverse links must be built from the full KB dataset, not only from the current search result subset. Otherwise a clicked issue could show an incomplete `See Also` section depending on the current search query.

### Risk: malformed `SeeAlso` source values

The workbook may contain:

- inconsistent casing
- extra spaces
- duplicate IDs
- self-references

These should all be normalized centrally in the backend.

### Risk: title changes or missing titles

If a related issue exists but has a blank title, the UI should still be able to render the `IssueID`. This is a minor data-quality case and should not block the link from being shown.

## Recommended Implementation Sequence

1. Extend KB load-time normalization for `SeeAlso`.
2. Build a full-dataset bidirectional related-issue map.
3. Add `SeeAlsoResolved` to KB search responses.
4. Update the KB detail renderer to insert `See Also` before `Tags`.
5. Wire click behavior to the existing KB issue-navigation flow.
6. Add backend tests for resolution, uniqueness, and reverse-link generation.
7. Update `requirements.md`.
8. Manually verify with one-way and two-way `SeeAlso` examples.

## Acceptance Criteria

- Expanded KB issues show a `See Also` section when related issues exist.
- The section appears before `Tags`.
- Each item displays a unique related issue ID and title.
- Clicking a related issue loads that issue in the Knowledge Base view.
- One-way `SeeAlso` references are displayed bidirectionally.
- Duplicate related entries are not shown.
- Backend tests cover resolved relationships and reverse-link generation.
- `requirements.md` documents the new behavior.
