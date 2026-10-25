"""Read the document behind an input proxy before any verified replacement."""

import json


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
