# Resolve field labels to text inputs before typing

## Report and cause

The Feishu custom-app dialog report used public SDK 0.58.16 and extension
0.4.9. Its Name textbox had the accessible name `0/32`; searching for `Name`
selected a surrounding div instead. All three fill methods ran against that
div. Its existing text caused `typed=true` even though verification failed and
the real input stayed empty.

The typing implementation is unchanged between the reported package and
0.58.17. Before the correction, two real Chrome regressions failed: a dialog
label selected a button/container instead of the textbox, and a multi-input
wrapper attempted all methods and reported `typed=true, verified=false`.

## Contract

- Text clicks and text discovery retain their existing target selection.
  Typing resolves actual text inputs, textareas and contenteditable hosts.
- A unique exact accessible field name takes precedence. Otherwise, a label
  control or matching field wrapper may resolve one contained text field.
  Nested dialog matches narrow to their matching field group. Resolution
  never climbs into an unrelated ancestor, sibling or frame.
- Multiple matching fields return `conflict`; a noneditable target returns
  `validation`. Both report `typed=false`, `verified=false`, `input_sent=false`
  and an empty `methods_tried`, before clearing, focusing or typing.
- A direct ref identifies that exact field. A wrapper ref is refused, even
  when its existing text already equals the requested value. Only label
  lookup resolves a contained input; its returned ref identifies that input.
- The shared verified-fill actuator still owns typing, model verification,
  fallbacks and Enter. Rich-editor model handling, hidden-page checks and
  extension ownership guards remain in that path.

The DOM resolver is read-only and pins the selected DOM identity through CDP.
It does not add page attributes, write values, dispatch synthetic input or
move focus. Plain-field preflight shares one type predicate across locators
and the existing verified-fill implementation.

## Live acceptance

Generated scenarios live in `tests/integration/scenarios_label_typing.json`.
Their shared journeys use a neutral HTTP app-creation form, real Chrome,
the bundled extension and fresh CLI subprocesses. No authenticated Feishu
page, production application, user's profile or shared bridge is changed.

The successful workflow fills Name through a wrapper despite an identically
named button, then fills a multiline description, HTML label, placeholder,
contenteditable and same-origin iframe field. It verifies the actual target
ref, trusted input events, exactly one HTTP submission and a rendered final
PNG. The CDP path and both extension WebSocket implementations run this flow.

The refusal workflow preserves a focused sentinel input while attempting a
two-input wrapper, duplicate field names, duplicate wrappers with different
character counters, static text, and a direct wrapper ref with exactly its
existing text. It requires no input events, no extension `Input.*` commands,
no accidental value property, unchanged fields/focus and zero submissions.

The three-platform E2E job and the Linux/Windows real-extension job execute
these generated tests and retain JSON/PNG evidence. Real logged-in Feishu
retesting remains a consumer confirmation of this neutral reproduction.

## CLI steering audit

Core docstrings remain the source for Python help, actual `--help`, and runtime
failure hints. The opening paragraphs distinguish label resolution from a
direct field ref and describe the returned verification and target ref.
Failures direct the caller to `page_discover` and `type_by_ref`, with a stable
error category and `retryable=false`; they do not advise replaying an ambiguous
label. Both tools keep their existing names and parameters. All 63 generated
tool wrappers remain byte-for-byte unchanged; 136 CLI/guard checks pass.
