# Knowledge Base Active-Tags Multi-Select Analysis

## Summary

The Knowledge Base tab currently has three search inputs:

- `Issue ID`
- `Asset Tag`
- `Search all fields`

The request is to add a new search field to the Knowledge Base UI that is a multi-select dropdown containing all unique tags found on active issues.

This feature affects:

- Knowledge Base tab markup in [frontend/index.html](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/index.html:172)
- Knowledge Base search logic in [frontend/script.js](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/script.js:218)
- knowledge base data normalization and search API behavior in [backend/main.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/backend/main.py:84) and [backend/main.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/backend/main.py:840)
- tests in [tests/run_tests.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/tests/run_tests.py:472)
- requirements in [requirements.md](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/requirements.md:82)

## Current State

### Frontend

The Knowledge Base tab markup is currently:

- `kbIssueIdSearch`
- `kbTagSearch`
- `kbFreeformSearch`
- `searchKnowledgeBaseBtn`

See [frontend/index.html](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/index.html:172).

The current search flow in [frontend/script.js](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/script.js:218) does the following:

- reads the three text inputs
- requires at least one non-empty criterion
- sends `/knowledgebase/search` with optional query params:
  - `issue_id`
  - `tag`
  - `freeform`

The current tag field is a free-text single tag input, not a selectable list. The new feature is therefore an additional search field, not a replacement for the existing free-text filters.

### Backend

The knowledge base loader in [backend/main.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/backend/main.py:84) currently:

- loads the `Issues` sheet
- normalizes `AppliesToAssetTag`
- creates `AppliesToAssetTagNorm` as a single uppercase comma-separated string

The search endpoint in [backend/main.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/backend/main.py:840) currently supports:

- `issue_id`
- `tag`
- `freeform`

The tag filter currently assumes one tag:

- it uppercases the query value
- splits each issue row’s `AppliesToAssetTagNorm` on commas
- matches exact tag membership

There is currently no endpoint that returns the distinct set of knowledge-base asset tags for use in a dropdown.

### Tests

Existing knowledge base tests cover:

- search by issue id
- search by tag
- freeform search
- required fields in search results

See [tests/run_tests.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/tests/run_tests.py:472).

### Requirements

The current requirements say the Knowledge Base tab provides three search fields in [requirements.md](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/requirements.md:82):

- IssueID
- Tag (Asset Tag)
- freeform text

They do not define:

- a multi-select tag control
- a source of selectable tag values
- how multiple selected tags should be combined
- how the `Active` workbook column drives selectable tag values

## Confirmed Product Decisions

The product decisions are now clarified:

1. The multi-select is a new additional field on the Knowledge Base tab.
   It does not replace the existing KB search inputs.

2. “Active issues” is defined by the `Active` column in the knowledge base data source.
   Valid values are `Yes` and `No`.

That removes the earlier ambiguity around both UI shape and data source semantics.

## Recommended Design

## UI Recommendation

Add a new multi-select dropdown alongside the existing KB search controls, populated from backend-derived KB tag options.

Recommended UI controls on the Knowledge Base tab:

- `Issue ID` text input
- existing `Asset Tag` text input
- new `Active Issue Tags` multi-select dropdown
- `Search all fields` text input
- `Search` button

This aligns with the existing app pattern because the UI already uses native multi-select controls elsewhere.

## Backend Recommendation

Add a dedicated endpoint that returns all selectable KB tag options, for example:

- `/knowledgebase/tags`

Recommended response shape:

```json
{
  "tags": [
    { "value": "ZVVU-A001", "label": "ZVVU-A001" }
  ]
}
```

Then update `/knowledgebase/search` to accept multiple tags, for example:

- repeated query params:
  - `tag=ZVVU-A001&tag=ZVKU-A001`
- or a comma-separated `tags` parameter

I recommend repeated `tag` query parameters because:

- `URLSearchParams.append("tag", value)` already maps well from the frontend
- it avoids extra parsing rules
- it keeps the current param name conceptually intact

Search semantics should be:

- OR across selected tags
- OR between the existing free-text `Asset Tag` field and the new active-issue-tags multi-select
- OR with the other filter groups (`issue_id` and `freeform`)

That means any issue matching any supplied criterion should be returned.

## Required Backend Changes

### 1. Normalize KB tag values into a reusable structure

The current loader only stores:

- raw `AppliesToAssetTag`
- uppercase string `AppliesToAssetTagNorm`

That is enough for single-tag filtering but not ideal for building dropdown options.

Recommended backend normalization additions in [backend/main.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/backend/main.py:84):

- parse each issue’s comma-separated `AppliesToAssetTag` into normalized individual tags
- preserve canonical display casing
- derive a sorted unique list of KB tag options from rows where `Active == "Yes"`

This can be computed:

- once at load time
- and refreshed during `/data/reload`

### 2. Add a KB tag-options endpoint

Add a new endpoint, for example:

- `/knowledgebase/tags`

Behavior:

- return all unique tag values found on KB issue rows where `Active == "Yes"`
- sorted case-insensitively
- omit blanks

### 3. Extend KB search to support multiple tag filters

Update [backend/main.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/backend/main.py:840) so the search endpoint can accept multiple tag selections.

Recommended rule:

- treat the existing free-text `tag` parameter and the new multi-select tag selections as one combined tag filter group
- evaluate each active criterion group independently:
  - `issue_id`
  - free-text `tag`
  - multi-select tags
  - `freeform`
- if no criteria are supplied, return the current validation error
- if one or more criteria are supplied, include issues matching any active criterion group

This is an OR match across:

- `issue_id`
- all selected multi-select tags
- the existing free-text tag input
- `freeform`

### 4. Keep existing single-tag compatibility only if needed

If the frontend is fully updated and no other callers rely on single-tag search, the endpoint can move cleanly to multi-tag support. If compatibility matters, it can accept:

- one `tag`
- or many `tag` params

That is backward compatible and low risk.

## Required Frontend Changes

### 1. Update KB tab markup

Modify [frontend/index.html](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/index.html:174).

Add a new select element alongside the existing controls, for example:

- `<select id="kbActiveIssueTags" multiple></select>`

The existing `kbTagSearch` text input should remain in place unchanged.

### 2. Load tag options for the dropdown

The frontend will need a new initialization path in [frontend/script.js](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/script.js:218) to:

- fetch `/knowledgebase/tags`
- populate the multi-select
- preserve selected values if the list is reloaded after `/data/reload`

This should happen:

- on page load
- and after successful data reload

### 3. Update KB search request building

The current KB search code only reads string values from:

- `kbIssueIdSearch`
- `kbTagSearch`
- `kbFreeformSearch`

New logic should:

- keep reading the existing text inputs unchanged
- read `selectedOptions` from the new multi-select
- append each selected tag to `URLSearchParams`
- keep current behavior for `issue_id`, free-text `tag`, and `freeform`

If both the free-text tag field and the multi-select contain values, they must be combined with OR semantics.

### 4. Update validation logic

The current “at least one search criterion” check in [frontend/script.js](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/script.js:230) must consider:

- selected tag count > 0 in addition to the existing text inputs

instead of just a non-empty text field.

### 5. Update Enter-key handling expectations

The current Enter-key binding is attached to text inputs only in [frontend/script.js](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/frontend/script.js:255).

A native multi-select does not use Enter the same way as text inputs. The practical behavior should be:

- Enter still works from `Issue ID`
- Enter still works from `Search all fields`
- changing the multi-select does not auto-submit unless explicitly desired

That is acceptable, but the requirement language should be updated to reflect the presence of a non-text input.

### 6. Styling impact

The existing `.search-section` layout in the KB tab will need to accommodate a taller multi-select control. This is likely a small CSS adjustment rather than a redesign.

## Search Semantics Recommendation

Recommended combined logic:

- `issue_id`: partial match, case-insensitive
- `freeform`: existing normalized freeform search
- tag filters: OR across:
  - the existing free-text tag field
  - all selected multi-select tags
- all active filter groups combine with OR

Example:

- `issue_id=KB`
- `freeform=audio`
- selected tags = `["ZVVU-A001", "ZVKU-A001"]`

Result:

- issues matching the issue id filter
- or matching the freeform filter
- or containing at least one tag from the combined tag filter set

## Impact on Reload Behavior

The repo already has `/data/reload` and frontend reload handling. Because KB tag options are derived from KB data, the feature should explicitly include tag-option refresh after reload.

Impact:

- when KB data changes, the dropdown options may change
- the frontend should re-fetch KB tag options after a successful reload
- existing selections should be preserved if they still exist
- invalidated selections should be dropped cleanly

## Required Test Changes

New and modified tests are required.

### Backend Tests to Add

Add tests in [tests/run_tests.py](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/tests/run_tests.py:472):

1. `test_knowledgebase_tags_endpoint_returns_list`
   - call `/knowledgebase/tags`
   - verify response contains a non-empty `tags` list
   - verify each option has a non-empty value

2. `test_knowledgebase_tags_endpoint_unique_sorted`
   - verify returned tag values are unique
   - verify they are sorted case-insensitively

3. `test_knowledgebase_search_multiple_tags`
   - call `/knowledgebase/search` with repeated tag params
   - verify the endpoint returns a list
   - verify each returned issue contains at least one selected tag

4. `test_knowledgebase_search_tag_and_freeform_combination`
   - verify multi-tag filtering combines with freeform search using OR semantics

### Existing Tests to Modify

1. Update `test_knowledgebase_search_by_tag`
   - keep it, but make it validate the new multi-tag-capable API contract
   - a single repeated `tag` param should still work

2. Keep the existing:
   - issue-id test
   - freeform test
   - required-fields test

These should continue to pass with the new feature.

### Manual Frontend Verification

Because there is no automated frontend test harness in the repo, manual verification should be part of acceptance:

- KB tab shows a multi-select of asset tags
- options match actual KB issue tags
- selecting one tag filters correctly
- selecting multiple tags widens results correctly
- Issue ID and freeform still work with the multi-select
- reload refreshes the available tag options

## Requirements Updates Needed

Update [requirements.md](/Users/donert/Documents/UACTech/SystemDocumentation/github/uactechdoc/webapp/requirements.md:82).

### Replace current KB search-field language

Current language says:

- three search fields: IssueID, Tag, and freeform text

Recommended revised language:

> The Knowledge Base tab provides search controls for IssueID, Asset Tags, and freeform text search. Asset Tags must be presented as a multi-select dropdown populated with all unique asset tags associated with active knowledge base issues. Selecting multiple asset tags must match issues associated with any of the selected tags. Pressing Enter in the text search fields must trigger the search, as does clicking the Search button.

### Add definition of tag-option source

The requirements should also define what the dropdown is populated from:

- if “active issues” means all searchable issues, say so directly
- if there is a workbook status field, specify that only active/open issues contribute tag options

Without that clarification, implementation will otherwise have to infer behavior.

## Risks and Decisions

### Decision: define “active issues”

This must be clarified. If not clarified, the default implementation should interpret active issues as:

- all currently searchable KB issue rows with non-empty `IssueID`

### Risk: inconsistent tag formatting in workbook rows

The workbook uses comma-separated `AppliesToAssetTag` values. If spacing or casing is inconsistent, option derivation and filtering must normalize tags carefully. This is manageable, but it should be handled centrally in backend normalization rather than ad hoc in the endpoint.

### Resolved semantic rule: all KB search criteria use OR

The existing free-text Asset Tag field, the new active-issue-tags multi-select, `Issue ID`, and freeform text search must all be treated with OR semantics. That means an issue is included if it matches any supplied search criterion.

### Risk: native multi-select usability

A plain HTML multi-select is the simplest implementation and matches existing patterns in the app, but it is not the most polished control. If the product expects a searchable tokenized dropdown, that is a broader UI enhancement than this feature request currently states.

## Recommended Implementation Sequence

1. Define whether the multi-select replaces the existing KB tag text input.
2. Define what “active issues” means.
3. Add backend KB tag normalization and unique-option derivation.
4. Add `/knowledgebase/tags`.
5. Extend `/knowledgebase/search` to accept multiple tags.
6. Update KB tab markup and search logic.
7. Refresh KB tag options after `/data/reload`.
8. Add backend tests and perform manual UI verification.
9. Update `requirements.md`.

## Acceptance Criteria

- The Knowledge Base tab includes an asset-tag multi-select dropdown.
- The dropdown is populated with unique tags derived from active/searchable KB issues.
- Selecting one or more tags filters search results correctly.
- Multi-tag filtering works together with Issue ID and freeform search.
- The tag options refresh when KB data is reloaded.
- Tests cover the new tag-options endpoint and multi-tag search behavior.
- `requirements.md` is updated to describe the control and its semantics.
