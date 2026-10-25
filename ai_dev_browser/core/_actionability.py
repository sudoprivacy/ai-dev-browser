"""One read-only definition of a visible, reachable element hit target."""

ACTIONABILITY_JS = r"""
function __parent(n) {return n.parentElement || (n.getRootNode && n.getRootNode().host) || null;}
function __contains(a,b) {for(var n=b;n;n=__parent(n)) if(n===a)return true;return false;}
function __styleReason(el) {
  if(!el || !el.isConnected)return 'detached';
  for(var n=el;n;n=__parent(n)){
    var s=n.ownerDocument.defaultView.getComputedStyle(n);
    if(s.display==='none'||s.visibility==='hidden'||s.visibility==='collapse'||s.contentVisibility==='hidden'||Number(s.opacity)===0)return 'hidden';
    if(n.inert)return 'inert';
  }
  return null;
}
function __clipped(el) {
  var r=el.getBoundingClientRect(),win=el.ownerDocument.defaultView;
  var b={left:Math.max(0,r.left),top:Math.max(0,r.top),right:Math.min(win.innerWidth,r.right),bottom:Math.min(win.innerHeight,r.bottom)};
  for(var n=__parent(el);n;n=__parent(n)){
    var s=win.getComputedStyle(n),p=n.getBoundingClientRect();
    if(/hidden|clip|auto|scroll/.test(s.overflowX)){b.left=Math.max(b.left,p.left);b.right=Math.min(b.right,p.right);}
    if(/hidden|clip|auto|scroll/.test(s.overflowY)){b.top=Math.max(b.top,p.top);b.bottom=Math.min(b.bottom,p.bottom);}
  }
  return b;
}
function __hit(el,x,y,frameLocal){
  var root=el.getRootNode(),doc=el.ownerDocument;
  var hit=(root.elementFromPoint ? root : doc).elementFromPoint(x,y);
  while(hit && hit.shadowRoot){var child=hit.shadowRoot.elementFromPoint(x,y);if(!child||child===hit)break;hit=child;}
  if(!__contains(el,hit))return null;
  var win=doc.defaultView;
  while(!frameLocal && win!==win.top){
    var frame;
    try{frame=win.frameElement;}catch(e){return null;}
    if(!frame)return null;
    var r=frame.getBoundingClientRect();
    x=r.left+(frame.clientLeft+x)*(r.width/frame.offsetWidth);
    y=r.top+(frame.clientTop+y)*(r.height/frame.offsetHeight);
    if(__styleReason(frame))return null;
    var b=__clipped(frame);
    if(x<b.left||x>=b.right||y<b.top||y>=b.bottom)return null;
    if(frame.ownerDocument.elementFromPoint(x,y)!==frame)return null;
    win=frame.ownerDocument.defaultView;
  }
  return {x:x,y:y};
}
function __actionState(original,target,scroll,frameLocal,preferred){
  original=original && (original.nodeType===1 ? original : original.parentElement);
  target=target && (target.nodeType===1 ? target : target.parentElement);
  var reason=__styleReason(original);
  if(reason)return {found:!!original,visible:false,actionable:false,reason:reason};
  if(scroll && target){try{target.scrollIntoView({block:'nearest',inline:'nearest'});}catch(e){}}
  var originalRect=original.getBoundingClientRect(),own=__clipped(original);
  if(originalRect.width>0 && originalRect.height>0 && (own.right<=own.left||own.bottom<=own.top))
    return {found:true,visible:false,actionable:false,reason:'clipped'};
  reason=__styleReason(target);
  if(reason)return {found:!!target,visible:false,actionable:false,reason:reason};
  var r=target.getBoundingClientRect(),b=__clipped(target);
  var result={found:true,tag:target.tagName.toLowerCase(),x:b.left,y:b.top,w:Math.max(0,b.right-b.left),h:Math.max(0,b.bottom-b.top)};
  result.visible=result.w>0 && result.h>0;
  result.actionable=false;
  if(!result.visible){result.reason='no_visible_layout';return result;}
  if(target.disabled||target.getAttribute('aria-disabled')==='true'){result.reason='disabled';return result;}
  var points=[[.5,.5],[.25,.25],[.75,.25],[.25,.75],[.75,.75]];
  if(preferred)points.unshift(preferred);
  for(var p of points){
    var x=b.left+result.w*p[0],y=b.top+result.h*p[1],global=__hit(target,x,y,frameLocal);
    if(global){result.actionable=true;result.point=global;return result;}
  }
  result.reason='covered_or_not_hit_target';return result;
}
"""


async def element_actionability(element):
    return await element.apply(
        "(el)=>{" + ACTIONABILITY_JS + "return __actionState(el,el,false);}"
    )


def click_refusal(state):
    """Stable pre-input failure shared by every element locator."""
    return {
        "clicked": False,
        "verified": False,
        "method": None,
        "visible": state.get("visible", False),
        "actionable": False,
        "input_sent": False,
        "error_code": "conflict",
        "retryable": False,
        "error": "The requested element has no usable visible hit target ("
        + str(state.get("reason", "unavailable"))
        + "). Show or expand it and remove overlays before clicking; no input was sent.",
    }
