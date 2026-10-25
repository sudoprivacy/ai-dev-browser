# Feishu editor and navigation BR — 2026-10-25

## Verified editor replacement

Monaco's textarea is an input proxy. Its value can be empty or contain a small
selection while the document contains hundreds of lines. The previous fill
ladder cleared and verified that proxy, then retried against the actual editor.
In an unchanged `d461f88` checkout with official Monaco 0.55.1, a 308-character
request produced an 8,934-character document retaining the original example.

The shared fill primitive now identifies known editor proxies before clearing.
For Monaco with a public editor registry, it resolves the editor whose DOM root
contains the selected proxy and pins that editor, model and document version.
One `executeEdits` call replaces the full model range, bracketed by undo stops.
It compares the complete resulting model with the requested text in the page.
The return reports `method="editor"` and `verification="editor_model"`.

A single trusted `insertText` after selecting all still triggered Monaco's
automatic indentation during local acceptance. The explicit model edit gives
bulk JSON replacement exact text semantics with bracket completion and
auto-indent enabled. It does not claim to produce trusted keyboard events.

A private, read-only or unavailable editor model returns `unsupported` before
editing. Other recognized rich editor proxies without an adapter are also
refused. An application-rejected or changed model returns a non-retryable
conflict. Editor writes do not fall through to keys or a proxy value setter.
Both typing tools send an explicitly requested Enter only after verification.
Ordinary input and textarea fills retain their existing verified methods.

Feishu's exact Monaco version and module exposure were not established by this
BR. An app that keeps Monaco's API private receives the safe unsupported result;
a caller can then use a documented app-specific full-document API and verify it.
No Feishu app configuration, credential or server mutation was used for testing.

## Visible hit targets

The unchanged baseline also reproduced `clicked=true, verified=true` on a
collapsed link, with no navigation and a click landing on an adjacent control.
Positive layout dimensions did not establish that the requested link was usable.

Discovery and element clicks now share one actionability implementation. It
checks ancestor visibility, clipping, disabled state and an actual hit point.
Same-origin frame coordinates include frame borders and transforms; open and
closed shadow roots are covered. Human movement and its shared random offset
remain in use, with the selected offset checked before dispatch.

Ref, text, ID, XPath and row clicks use this check. Hidden or covered targets
return `clicked=false`, `verified=false`, `input_sent=false`, `error_code=conflict`
and `retryable=false` before entering any fallback. Discovery adds `visible`,
`actionable` and `actionability_reason` without scrolling or changing the DOM.
These are pointer observations; a missing observation remains null.

For ref/text clicks, `verified` means an observable page change followed a
click on a usable hit target. Navigation is reported separately. Application
transactions still require their own outcome checks. Core docstrings supply
this definition and recovery instructions to actual CLI help and error hints.
All 63 generated tool interfaces retain their signatures.

The previous overlay regression expected a synthetic click through the cover.
Its replacement first proves no event reaches the blocked target, then closes
the overlay through its visible button and checks one trusted target click.

## Regression evidence

Generated scenarios are defined in `tests/integration/scenarios_editor_click.json`.
They use the official npm Monaco archive pinned by SHA-512 and a local HTTP
fixture. The archive cache is verified on every load; transport retries apply
only to the read-only dependency download.

The journeys cover short and long JSON, two independent editors, ordinary
fields, private model refusal, application restoration after an edit, CLI error
receipts, collapsed and covered controls, real SPA navigation, non-navigation
actions, scaled iframes and open/closed shadow roots. Python calls and real CLI
processes use both extension WebSocket backends; standalone CDP is also tested.

Local live PTY compatibility acceptance passed 68 checks with zero skips,
including the initial editor regressions, ordinary verified fills, trusted
clicks, DOM discovery, recording feedback, key handling and wait workflows.
Final acceptance of all ten generated scenarios passed 16 checks with zero
skips: 15 actual browser journeys and one import check. The real CLI performed
the first full replacement on each extension backend, refused private models
without editing or Enter, and returned the hidden-target error code and hint.
Each successful replacement produced exactly one model change.
The final unit/bridge/retry suite passed 271 checks, including the 69 CLI
steering contracts. Ownership and hidden-page refusals stop before editing or
advancing to another query or input method.

CI runs the generated CDP cases on the three standard hosts and the extension
cases in all three real-extension environments. It retains JSON ledgers and
rendered PNGs. Local receipts, including failed baselines and the dependency
download failure, are under `scratch/feishu-interaction-20261025`.

## Other observations in the report

Native occlusion remains a genuine hidden-input refusal. Document focus alone
does not prove visibility; this change adds no visibility emulation or input
bypass.

Closing the original automation tab intentionally invalidates a strict binding
to that page. Source review confirms an unbound `browser_connect` can inspect
the current session and owned targets. Recovery must compare the persisted
session/profile and select the exact surviving owned target explicitly. It
must not treat a new blank main page as continuation or adopt unrelated tabs.
This separate recovery observation was not reproduced against the real Feishu
session and is not presented as a newly fixed lifecycle defect.
