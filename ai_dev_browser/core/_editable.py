"""Resolve text fields and read editor documents before verified replacement."""

import json

from ai_dev_browser.cdp import dom, runtime

from ._element import Element
from ._js import unwrap

_TEXT_ENTRY = """
function textEntry(n) {
  if (!n || n.nodeType !== 1 || !n.isConnected) return false;
  if (n.localName === 'textarea') return !n.disabled;
  if (n.localName === 'input') return !n.disabled &&
    !['button','checkbox','radio','file','hidden','image','range','reset','submit','color'].includes(n.type);
  return n.isContentEditable && !(n.parentElement && n.parentElement.isContentEditable);
}
"""


def typing_refusal(reason):
    """One pre-input failure contract shared by label lookup and direct refs."""
    return {
        "typed": False,
        "verified": False,
        "method": None,
        "methods_tried": [],
        "input_sent": False,
        "error_code": "conflict" if reason == "ambiguous" else "validation",
        "retryable": False,
        "error": (
            "The label matches multiple text fields; no typing or Enter was sent."
            if reason == "ambiguous"
            else "The target is not a text input, textarea or contenteditable host; no typing or Enter was sent."
        ),
    }


async def is_text_entry(element):
    """Read the actual DOM type before clearing, focusing or dispatching input."""
    return await element.apply("(el)=>{" + _TEXT_ENTRY + "return textEntry(el);}")


async def resolve_text_entry(element, query):
    """Return (field, refusal, exact_label) without moving focus.

    Keep the returned DOM identity pinned with CDP, rather than tagging the
    page or later re-running a selector that could target a different field.
    Never climb to an unrelated ancestor, document, sibling or frame.
    """
    script = (
        "function(){"
        + _TEXT_ENTRY
        + r"""
const normal=s=>s.trim().replace(/\s+/g,' ').toLowerCase();
const query=normal(QUERY);
function labelText(n) {
  if(n.nodeType===3) return n.nodeValue;
  if(n.nodeType!==1 || textEntry(n) || n.matches(
      'button,a,select,script,style,[role=button],[role=link],[hidden],[aria-hidden=true]')) return '';
  return Array.from(n.childNodes).map(labelText).join('');
}
function result(field,reason,scope) {
  const text=normal(labelText(scope));
  // Required markers and their character counters decorate a field label.
  // Keep the entire label: a nested word in "Legal Name" is not exact "Name".
  const label=text.replace(/\s*\*\s*(?:\d+\s*\/\s*\d+\s*)?$/,'').trim();
  return {field,reason,exact:text===query || label===query};
}
const el=this.nodeType===3 ? this.parentElement : this;
if(!el || !el.querySelectorAll) return 'not_editable';
if(textEntry(el)) return {field:el,exact:false};
const label=el.closest && el.closest('label');
if(label && textEntry(label.control)) return result(label.control,null,label);
""".replace("QUERY", json.dumps(query))
        + "const fields=n=>Array.from(n.querySelectorAll('input,textarea,[contenteditable]')).filter(textEntry);"
        "let scope=el;"
        # An outer dialog may include the label too. Narrow to its matching
        # field group rather than treating every input in the dialog as labelled.
        "while(scope.children){"
        " const groups=Array.from(scope.children).filter(n=>"
        "   (n.textContent||'').toLowerCase().includes(query) && fields(n).length);"
        " if(groups.length!==1) break; scope=groups[0];}"
        "const found=fields(scope);"
        "if(!found.length) return 'not_editable';"
        "return result(found.length===1 ? found[0] : null,"
        " found.length===1 ? null : found.length ? 'ambiguous' : 'not_editable',scope);}"
    )
    source = await element._resolve()
    target, error = await element.tab.send(
        runtime.call_function_on(
            script, object_id=source.object_id, return_by_value=False
        )
    )
    if error:
        unwrap(target, error, expression=script)
    if not target.object_id:
        return None, target.value or "not_editable", False
    field = None
    try:
        properties, _, _, error = await element.tab.send(
            runtime.get_properties(target.object_id, own_properties=True)
        )
        if error:
            unwrap(target, error, expression=script)
        values = {p.name: p.value for p in properties if p.value is not None}
        field = values.get("field")
        exact = bool(values["exact"].value)
        if field is None or field.subtype != "node":
            return None, values["reason"].value, exact
        node = await element.tab.send(dom.describe_node(object_id=field.object_id))
        return Element(node, element.tab), None, exact
    finally:
        if field and field.object_id:
            await element.tab.send(runtime.release_object(field.object_id))
        await element.tab.send(runtime.release_object(target.object_id))


_EDITOR_MODEL = """
var root = el && el.closest && el.closest('.monaco-editor');
var proxy = el && el.closest && el.closest('.CodeMirror,.cm-editor,.ace_editor,.ProseMirror,[data-slate-editor],[data-lexical-editor],.ql-editor');
if (!root) return {kind:proxy ? 'unsupported' : 'plain'};
var win = el.ownerDocument.defaultView, api = win.monaco;
if (!api || !api.editor || typeof api.editor.getEditors !== 'function')
  return {kind:'monaco',supported:false};
var editor = api.editor.getEditors().find(e => e.getDomNode() === root);
var model = editor && editor.getModel();
if (!model || model.isDisposed()) return {kind:'monaco',supported:false};
var readonly = editor.getOption(api.editor.EditorOption.readOnly);
var state = {kind:'monaco',supported:!readonly,readonly:readonly,
  editor_id:editor.getId(),model_id:model.id,version:model.getVersionId()};
"""


async def editor_state(element):
    """Identify a readable editor and model without returning document contents."""
    return await element.apply("(el)=>{" + _EDITOR_MODEL + "return state;}")


async def replace_editor_document(element, text, expected):
    """One atomic public editor edit, preserving undo and rejecting model races."""
    script = (
        _EDITOR_MODEL
        + "var expected="
        + json.dumps(expected)
        + ";"
        + "var text="
        + json.dumps(text)
        + ";"
        "state.same_model=state.editor_id===expected.editor_id && state.model_id===expected.model_id;"
        "state.applied=false;"
        "if(state.supported && state.same_model && state.version===expected.version){"
        "editor.pushUndoStop();"
        "state.applied=editor.executeEdits('ai-dev-browser',[{range:model.getFullModelRange(),text:text,forceMoveMarkers:true}]);"
        "editor.pushUndoStop();}"
        "state.matches=state.same_model && editor.getModel()===model && !model.isDisposed() && model.getValue()===text;"
        "return state;"
    )
    return await element.apply("(el)=>{" + script + "}")
