# Prefer associated field labels over background substring matches

## Report and reproduction

The original Feishu consumer retested public SDK 0.58.18 and extension 0.4.9
on 2026-11-09. The running bridge version was verified after a supported
reconnect. The original Name wrapper now resolved to its actual input, but
`type_by_text(name="Name", ...)` still returned `conflict`: a background input
named `Search by app name or App ID` also matched the discovery substring.
Description succeeded independently. The consumer canceled without creating
an application.

The previous neutral form covered a same-name button, unrelated search box,
duplicate fields and different character counters. Its search placeholder
did not contain Name, so it did not reproduce this remaining interaction.

Before this correction, the new real Chrome modal journey reproduced that
same pre-input conflict on the latest main branch (SDK 0.58.20) and independently
with the official 0.58.18 wheel, with checkout source excluded from imports.

## Selection contract

Typing now ranks exact accessible field names and exact associated field
labels together, ahead of longer substring matches. A wrapper label is read
from the same narrowed field group already used to resolve the editable node.
Input values, buttons, links, scripts and hidden label decorations are excluded
from its label text. A trailing required marker, optionally followed by its
character counter, decorates the label; it does not distinguish two Name fields.
The complete label is compared: a styled Name inside Legal Name is not an
exact Name label. No modal position, page order or fuzzy score selects a field.

Exact candidates are deduplicated by their actual DOM identity. Two exact
fields still return `conflict`, including an exact direct textbox competing
with an exact wrapped field. An exact label covering multiple fields also
blocks selection even when another exact direct textbox exists. If no exact
label exists, the existing unique-substring behavior remains; multiple
substring fields are refused.

Resolution is read-only and pins the returned field identity with CDP. Refusal
still returns `typed=false`, `verified=false`, `input_sent=false`, empty
`methods_tried`, `error_code=conflict`, and `retryable=false`, without clearing,
focusing, typing or Enter. Direct-ref validation and the shared verified-fill,
ownership, visibility and editor contracts remain in their existing owners.

## Live regression and tool guidance

`scenarios_label_typing.json` adds a modal journey to the existing generated
tests. It opens a real local HTTP app list, clicks Create Custom App, confirms
discovery includes the background substring input, fills Name and Description,
checks the returned field ref and trusted input events, and submits exactly
one HTTP receipt. It saves the rendered result as PNG and verifies that the
background search value and the separate Legal Name field were preserved.
Cancel closes the modal normally; a unique substring search still works when
no exact label matches. The modal scrolls normally on a small viewport.

The same journey then checks six ambiguity variants: direct versus wrapped
Name, two wrapped Name fields with different counters, an HTML label versus a
wrapped Name, one label containing two inputs, that ambiguous group alongside
another exact Name textbox, and two substring-only search inputs. Each must
preserve focus and all values, emit zero input events and extension Input
commands, and create no extra receipt.

The existing CDP and both real-extension WebSocket fixtures execute this
journey. The existing three-platform E2E and Linux/Windows extension CI jobs
already collect the generated module and retain JSON/PNG evidence.

The core `type_by_text` opening help explains exact-label precedence and
ambiguity refusal. The actual generated CLI uses this docstring; tool names,
parameters, return shapes and direct-ref recovery guidance stay shared with
the Python API. No additional tool or consumer locator workaround is required.

The authenticated Feishu page is a separate consumer acceptance. The original
Name-label BR should remain open until that caller confirms the same operation
on the original page with the released SDK and actual updated bridge runtime.
