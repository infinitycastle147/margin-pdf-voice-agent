import './graph-view.css';

const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const colors = {person:'#aa735d',organization:'#50745c',place:'#588386',product:'#a4864e',process:'#778752',concept:'#68819a',event:'#9b7691',metric:'#8d8060'};

export function mountGraph(host, {onConversation, onEnd, onMute}) {
  host.innerHTML = `
    <div class="atlas-heading"><div><span class="eyebrow">THE KNOWLEDGE ATLAS</span><h1>See the bigger <em>picture.</em></h1><p>Every connection has a source. Every conversation can add a little more.</p></div><div class="atlas-actions"><button id="graphRefresh" class="quiet-button">↻ Refresh</button><button id="graphExport" class="quiet-button">Export graph ↗</button></div></div>
    <div class="atlas-toolbar"><div><span class="atlas-doc-label">DOCUMENT</span><strong id="atlasDocument">Choose a PDF in Conversation</strong></div><div class="atlas-stats"><span><b id="atlasNodes">0</b> concepts and entities</span><span><b id="atlasEdges">0</b> relationships</span></div></div>
    <div class="atlas-layout"><div class="atlas-map"><div class="atlas-map-top"><span id="graphStatus" role="status">Choose a document to explore its graph.</span><div class="map-controls"><button id="zoomOut" aria-label="Zoom out">−</button><button id="zoomIn" aria-label="Zoom in">+</button><button id="graphFit">Fit graph</button></div></div><svg id="knowledgeSvg" class="knowledge-svg" viewBox="0 0 1000 680" aria-label="Document knowledge graph. Select a node or use the entity explorer." tabindex="0"><defs><marker id="edgeArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#9eae97"/></marker></defs><g id="graphDrawing"></g></svg><div id="graphEmpty" class="atlas-empty"><span>◎</span><h2>Knowledge takes shape here.</h2><p>Select a document and ask a question.<br>Relationships appear after their evidence is reviewed.</p><button class="quiet-button" id="graphStart">Go to conversation ↗</button></div><div class="map-legend"><span><i></i> Reviewed entities</span><span><i class="legacy-key"></i> Earlier concepts</span><span>Drag to pan · + / − to zoom</span></div></div>
    <aside class="atlas-inspector"><label for="entitySearch" class="field-label">EXPLORE THE CONNECTIONS</label><input id="entitySearch" type="search" placeholder="Find an entity…"><div id="entityResults" class="entity-results"></div><div id="graphInspector" class="graph-inspector"><div class="inspector-empty"><span>↖</span><h2>Follow a connection.</h2><p>Select an entity to see its neighborhood, or a relationship to inspect exactly what supports it.</p></div></div></aside></div>
    <div class="atlas-bottom"><span id="graphUpdated">Saved in Neo4j · Available across sessions</span><span id="graphLegacy"></span></div>
    <div id="atlasCall" class="atlas-call" hidden><span class="status-dot"></span><div><strong id="atlasCallStatus">Voice session active</strong><span>Keep talking while the graph grows.</span></div><button id="atlasMute" class="quiet-button" aria-pressed="false">Mute mic</button><button id="atlasBack" class="quiet-button">View transcript</button><button id="atlasEnd">End conversation ×</button></div>`;
  const $ = s => host.querySelector(s);
  let documentId = '', visible = false, graph = {nodes:[],edges:[]}, selected = null;
  let controller, loading = false, signature = '', positions = new Map(), view = {x:0,y:0,w:1000,h:680};
  let pageRequest = 0, panning, needsRefresh = false;
  const getNodes = () => graph.nodes;
  const getEdges = () => graph.edges;
  const label = id => graph.nodes.find(n => n.id === id)?.name || id;
  const setView = () => $('#knowledgeSvg').setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.h}`);
  function fit() {
    const ps = getNodes().map(n => positions.get(n.id)).filter(Boolean);
    if (!ps.length) { view = {x:0,y:0,w:1000,h:680}; setView(); return; }
    const minX = Math.min(...ps.map(p=>p.x))-130, minY = Math.min(...ps.map(p=>p.y))-100;
    const maxX = Math.max(...ps.map(p=>p.x))+130, maxY = Math.max(...ps.map(p=>p.y))+100;
    view = {x:minX,y:minY,w:Math.max(500,maxX-minX),h:Math.max(400,maxY-minY)}; setView();
  }
  function layout() {
    const nodes = getNodes(), edges = getEdges();
    const next = nodes.map((n,i) => ({id:n.id,...(positions.get(n.id) || {x:500+Math.cos(i*2.39996)*Math.sqrt(i+1)*120,y:340+Math.sin(i*2.39996)*Math.sqrt(i+1)*100})}));
    const map = new Map(next.map(n=>[n.id,n]));
    // A deterministic bounded layout pass. Large graphs keep the searchable spiral layout.
    if (next.length <= 350) for (let step=0; step<90; step++) {
      const forces = new Map(next.map(n=>[n.id,{x:0,y:0}]));
      for (let i=0;i<next.length;i++) for (let j=i+1;j<next.length;j++) {
        const a=next[i],b=next[j],dx=a.x-b.x||.1,dy=a.y-b.y||.1;
        const d2=Math.max(100,dx*dx+dy*dy),d=Math.sqrt(d2),f=Math.min(15,17000/d2);
        forces.get(a.id).x+=dx/d*f;forces.get(a.id).y+=dy/d*f;forces.get(b.id).x-=dx/d*f;forces.get(b.id).y-=dy/d*f;
      }
      for (const e of edges) {
        const a=map.get(e.source),b=map.get(e.target); if(!a||!b)continue;
        const dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy)||1,f=(d-260)*.012;
        forces.get(a.id).x+=dx/d*f;forces.get(a.id).y+=dy/d*f;forces.get(b.id).x-=dx/d*f;forces.get(b.id).y-=dy/d*f;
      }
      for (const n of next) {n.x+=forces.get(n.id).x;n.y+=forces.get(n.id).y;}
    }
    positions = map;
  }
  function draw() {
    const nodes=getNodes(), edges=getEdges(), query=$('#entitySearch').value.trim().toLowerCase();
    const groups = new Map();
    for (const edge of edges) {const key=[edge.source,edge.target].sort().join('|');if(!groups.has(key))groups.set(key,[]);groups.get(key).push(edge.id);}
    const edgeMarkup = edges.map(e => {
      const a=positions.get(e.source),b=positions.get(e.target); if(!a||!b)return '';
      const ids=groups.get([e.source,e.target].sort().join('|')),index=ids.indexOf(e.id),offset=(index-(ids.length-1)/2)*60;
      const dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy)||1;
      // Canonical normal keeps reciprocal directed edges on distinct curves.
      const direction=e.source<e.target?1:-1;
      const cx=(a.x+b.x)/2-dy/d*offset*direction,cy=(a.y+b.y)/2+dx/d*offset*direction;
      const sx=a.x+dx/d*55,sy=a.y+dy/d*24,tx=b.x-dx/d*75,ty=b.y-dy/d*30;
      const path=`M${sx},${sy} Q${cx},${cy} ${tx},${ty}`;
      const lx=(sx+2*cx+tx)/4,ly=(sy+2*cy+ty)/4;
      const active=selected?.id===e.id || (selected?.type==='node'&&(e.source===selected.id||e.target===selected.id));
      return `<g class="knowledge-edge ${e.type==='legacy'?'legacy-edge':''} ${active?'edge-selected':''}" data-edge="${esc(e.id)}" role="button" tabindex="0" aria-label="${esc(`${label(e.source)} ${e.relation} ${label(e.target)}`)}"><title>${esc(`${label(e.source)} → ${e.relation} → ${label(e.target)}`)}</title><path class="edge-hit" d="${path}"/><path class="edge-line" d="${path}" marker-end="url(#edgeArrow)"/><text x="${lx}" y="${ly-8}" text-anchor="middle">${esc(e.relation.length>30?e.relation.slice(0,29)+'…':e.relation)}</text></g>`;
    }).join('');
    $('#graphDrawing').innerHTML = edgeMarkup + nodes.map(n => {
      const p=positions.get(n.id); if(!p)return '';
      const matches=!query||`${n.name} ${(n.aliases||[]).join(' ')}`.toLowerCase().includes(query);
      return `<g class="knowledge-node ${selected?.id===n.id?'node-selected':''} ${n.type==='legacy'?'legacy-node':''} ${!matches?'node-dim':''}" transform="translate(${p.x},${p.y})" data-node="${esc(n.id)}" role="button" tabindex="0" aria-label="${esc(n.name)}, ${esc(n.kind)}"><title>${esc(n.name)}</title><rect x="-85" y="-29" width="170" height="58" rx="9"/><circle cx="-66" cy="-3" r="4" fill="${n.type==='legacy'?'#b8a47e':colors[n.kind]||colors.concept}"/><text x="-54" y="-3">${esc(n.name.length>21?n.name.slice(0,20)+'…':n.name)}</text><text class="node-kind" x="-54" y="14">${esc(n.kind)}</text></g>`;
    }).join('');
    renderResults();
  }
  function renderResults() {
    const query=$('#entitySearch').value.trim().toLowerCase();
    const found=getNodes().filter(n=>`${n.name} ${(n.aliases||[]).join(' ')}`.toLowerCase().includes(query));
    $('#entityResults').innerHTML=found.length?found.map(n=>`<button data-node="${esc(n.id)}" class="entity-result ${selected?.id===n.id?'chosen':''}"><i style="background:${n.type==='legacy'?'#b8a47e':colors[n.kind]||colors.concept}"></i><span>${esc(n.name)}</span><small>${esc(n.kind)}</small></button>`).join(''):`<p>${query?'No matching entities.':'Concepts and entities appear here as the graph grows.'}</p>`;
  }
  function evidenceHtml(edge) {
    return `<div class="inspector-relation"><span class="field-label">${edge.type==='legacy'?'EARLIER RELATIONSHIP':'DOCUMENT RELATIONSHIP'}</span><h2>${esc(label(edge.source))}<em>${esc(edge.relation)}</em>${esc(label(edge.target))}</h2>${edge.qualifiers?`<p class="qualifier"><strong>Scope & conditions</strong>${esc(edge.qualifiers)}</p>`:''}${edge.type==='legacy'?'<span class="review-badge legacy-badge">Earlier extraction · Not independently reviewed</span><p class="graph-explanation">Saved from a previous conversation. Check the source quote before relying on this connection.</p>':`<span class="review-badge">✓ Evidence reviewed</span><p class="graph-explanation">Model-reviewed against source context. Check the quotes to assess the claim.</p>`}</div><div class="evidence-list">${(edge.evidence||[]).map(c=>`<article><span class="field-label">SOURCE · PAGE ${esc(c.page_number)}</span><blockquote>${esc(c.quote)}</blockquote><button class="text-button" data-page="${esc(c.page_number)}">Read source page ↗</button></article>`).join('')}</div>`;
  }
  function detailsHtml(node) {
    return (node.details||[]).map(detail=>`<div class="graph-detail"><p class="graph-explanation">${esc(detail.text)}</p>${(detail.evidence||[]).map(c=>`<article><span class="field-label">SOURCE · PAGE ${esc(c.page_number)}</span><blockquote>${esc(c.quote)}</blockquote><button class="text-button" data-page="${esc(c.page_number)}">Read source page ↗</button></article>`).join('')}</div>`).join('');
  }
  function inspect() {
    pageRequest++;
    if(!selected)return;
    if(selected.type==='edge') {
      const edge=graph.edges.find(e=>e.id===selected.id); if(!edge)return;
      $('#graphInspector').innerHTML=evidenceHtml(edge);return;
    }
    const node=graph.nodes.find(n=>n.id===selected.id); if(!node)return;
    const neighbors=getEdges().filter(e=>e.source===node.id||e.target===node.id);
    $('#graphInspector').innerHTML=`<span class="field-label">${esc(node.kind.toUpperCase())}</span><h2>${esc(node.name)}</h2>${node.type==='legacy'?'<p class="graph-explanation">Earlier extraction · Not independently reviewed</p>':''}${detailsHtml(node)}${node.aliases?.length?`<p class="graph-explanation">Also called: ${node.aliases.map(esc).join(', ')}</p>`:''}<span class="field-label">${neighbors.length} CONNECTIONS</span><div class="neighbor-list">${neighbors.map(e=>`<button data-edge="${esc(e.id)}"><span>${esc(e.relation)} ${e.target===node.id?'←':'→'}</span><strong>${esc(label(e.source===node.id?e.target:e.source))}</strong><small>${e.evidence.length} source quote${e.evidence.length===1?'':'s'}${e.type==='legacy'?' · Earlier extraction':''}</small></button>`).join('')}</div>`;
  }
  function select(type,id) {selected={type,id};draw();inspect();}
  host.addEventListener('click', async event => {
    const node=event.target.closest('[data-node]'),edge=event.target.closest('[data-edge]'),page=event.target.closest('[data-page]');
    if(node)select('node',node.dataset.node);
    else if(edge)select('edge',edge.dataset.edge);
    else if(page) {
      const request=++pageRequest,doc=documentId;
      page.disabled=true;
      let source=host.querySelector('.source-page'); if(source)source.remove();
      source=document.createElement('div');source.className='source-page';source.textContent='Loading source page…';$('#graphInspector').append(source);
      try {
        const response=await fetch(`/api/documents/${encodeURIComponent(doc)}/pages/${page.dataset.page}`);
        if(!response.ok)throw new Error('Could not load the source page. Check the PDF service.');
        const result=await response.json(); if(request!==pageRequest||doc!==documentId)return;
        source.innerHTML=`<h3>Page ${esc(result.page_number)}</h3><pre>${esc(result.content)}</pre>`;
      }catch(error){if(request===pageRequest)source.textContent=error.message;}
      finally{page.disabled=false;}
    }
  });
  $('#knowledgeSvg').addEventListener('keydown', e => {if((e.key==='Enter'||e.key===' ')&&e.target.matches('[data-node],[data-edge]')){e.preventDefault();e.target.dispatchEvent(new MouseEvent('click',{bubbles:true}));}});
  const zoom = factor => {const w=view.w*factor,h=view.h*factor;if(w<150||w>40000)return;view={x:view.x+(view.w-w)/2,y:view.y+(view.h-h)/2,w,h};setView();};
  $('#zoomIn').onclick=()=>zoom(.8);$('#zoomOut').onclick=()=>zoom(1.25);$('#graphFit').onclick=fit;
  $('#knowledgeSvg').addEventListener('pointerdown', e=>{if(e.target.closest('[data-node],[data-edge]'))return;const matrix=$('#knowledgeSvg').getScreenCTM();if(!matrix)return;panning={x:e.clientX,y:e.clientY,v:{...view},scale:matrix.a};$('#knowledgeSvg').setPointerCapture(e.pointerId);});
  $('#knowledgeSvg').addEventListener('pointermove',e=>{if(!panning)return;view.x=panning.v.x-(e.clientX-panning.x)/panning.scale;view.y=panning.v.y-(e.clientY-panning.y)/panning.scale;setView();});
  $('#knowledgeSvg').addEventListener('pointerup',()=>{panning=null;});$('#knowledgeSvg').addEventListener('pointercancel',()=>{panning=null;});
  $('#entitySearch').oninput=draw;
  async function refresh() {
    if(!documentId||!visible)return;
    if(loading){needsRefresh=true;return;}
    loading=true; const doc=documentId; const requestController=new AbortController();controller=requestController;
    const timeout=setTimeout(()=>requestController.abort(),18000);
    $('#graphRefresh').disabled=true;$('#graphStatus').textContent='Reading saved knowledge…';
    try {
      const response=await fetch(`/documents/${encodeURIComponent(doc)}/graph`,{signal:requestController.signal});
      if(!response.ok)throw new Error(response.status===404?'Graph endpoint not found. Restart the updated voice service.':'Graph unavailable. Check Neo4j and the voice service.');
      const result=await response.json();if(doc!==documentId||controller!==requestController)return;
      const nextSignature=JSON.stringify(result);const changed=signature!==nextSignature;
      const first=!graph.nodes.length; graph=result;signature=nextSignature;
      const reviewed=graph.nodes.filter(n=>n.type==='entity').length, earlier=graph.nodes.filter(n=>n.type==='legacy').length;
      $('#atlasNodes').textContent=reviewed+earlier;$('#atlasEdges').textContent=graph.edges.filter(e=>e.type==='claim'||e.type==='legacy').length;
      $('#graphEmpty').hidden=graph.nodes.length>0;
      $('#graphStatus').textContent=reviewed?'Live graph · checks for updates every 5 seconds':earlier?'Earlier knowledge shown · new reviewed connections appear here as you talk':'No relationships yet. Ask about the document to begin.';
      $('#graphUpdated').textContent=graph.updated_at?`Last saved ${new Date(graph.updated_at).toLocaleString()} · Persists across sessions`:'Saved in Neo4j · Available across sessions';
      $('#graphLegacy').textContent=earlier?`${earlier} earlier concepts are shown in amber and were not independently reviewed.`:'';
      if(changed){if(first||getNodes().some(n=>!positions.has(n.id)))layout();draw();if(first)fit();inspect();}
    } catch(error) {
      if(doc!==documentId||controller!==requestController)return;
      const lastError=error.name==='AbortError'?'Graph request timed out. Use Refresh to try again.':error.message;
      $('#graphStatus').textContent=lastError+(graph.nodes.length?' Showing the last loaded graph.':'');
    } finally {
      clearTimeout(timeout);
      if(controller===requestController){loading=false;$('#graphRefresh').disabled=false;if(needsRefresh){needsRefresh=false;refresh();}}
    }
  }
  $('#graphRefresh').onclick=refresh;$('#graphStart').onclick=onConversation;$('#atlasBack').onclick=onConversation;$('#atlasEnd').onclick=onEnd;$('#atlasMute').onclick=onMute;
  $('#graphExport').onclick=()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(graph,null,2)],{type:'application/json'}));a.download='margin-knowledge-graph.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};
  setInterval(()=>{if(visible&&!document.hidden)refresh();},5000);
  return {
    setDocument(doc){const next=doc?.id||'';$('#atlasDocument').textContent=doc?.title||doc?.filename||'Choose a PDF in Conversation';if(next===documentId)return;controller?.abort();controller=null;loading=false;needsRefresh=false;documentId=next;graph={nodes:[],edges:[]};signature='';positions.clear();selected=null;pageRequest++;$('#entitySearch').value='';$('#graphDrawing').replaceChildren();$('#graphInspector').innerHTML='<p>Select an entity or relationship to inspect its sources.</p>';$('#graphEmpty').hidden=false;$('#atlasNodes').textContent='0';$('#atlasEdges').textContent='0';$('#graphLegacy').textContent='';$('#graphUpdated').textContent='Saved in Neo4j · Available across sessions';$('#graphStatus').textContent=next?'Loading saved knowledge…':'Choose a document in Conversation.';renderResults();refresh();},
    show(value){visible=value;host.hidden=!value;if(value)refresh();},
    refresh,
    updateVoice(active,status,muted){$('#atlasCall').hidden=!active;$('#atlasCallStatus').textContent=status;$('#atlasMute').textContent=muted?'Unmute mic':'Mute mic';$('#atlasMute').setAttribute('aria-pressed',String(muted));},
  };
}
