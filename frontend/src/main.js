import { PipecatClient, RTVIEvent } from '@pipecat-ai/client-js';
import { SmallWebRTCTransport } from '@pipecat-ai/small-webrtc-transport';
import './style.css';
import { mountGraph } from './graph-view.js';
import { createActivityReceiver } from './activity-stream.js';

const icons = {
  mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/>',
  doc: '<path d="M14 2H5v20h14V7zM14 2v6h5M8 12h8M8 16h6"/>',
  arrow: '<path d="M7 17 17 7M7 7h10v10"/>',
  upload: '<path d="M12 16V3M7 8l5-5 5 5M4 15v6h16v-6"/>',
  graph: '<circle cx="5" cy="12" r="3"/><circle cx="19" cy="5" r="3"/><circle cx="19" cy="19" r="3"/><path d="m8 11 8-5M8 13l8 5"/>',
};
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.arrow}</svg>`;
const $ = selector => document.querySelector(selector);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const json = value => JSON.stringify(value, null, 2) ?? 'No output returned.';
$('#app').innerHTML = `
<div class="shell">
  <header class="topbar"><a class="brand" href="/" aria-label="Margin home"><span class="brand-mark">m<span>·</span></span>margin<span class="brand-divider"></span><span class="brand-caption">THE DOCUMENT STUDIO</span></a><div class="top-meta"><span class="status-dot"></span> Voice + knowledge <span class="version">WORKSPACE / 01</span></div></header>
  <main>
    <nav class="screen-nav" aria-label="Workspace views"><button id="conversationTab" class="active" aria-current="page">◉ Conversation</button><button id="graphTab">${icon('graph')} Knowledge atlas <span>GROWS WITH YOU</span></button></nav>
    <div id="conversationScreen">
    <section class="intro"><div><div class="eyebrow">LESS SEARCHING. MORE UNDERSTANDING.</div><h1>A conversation.<br class="mobile-break"> <em>A little more clarity.</em></h1><p>Talk to your documents. Follow every step behind the answer.</p></div><button id="export" class="quiet-button">Export session ${icon('arrow')}</button></section>
    <div class="workspace">
      <aside class="sources panel"><div class="section-label"><span>01 / YOUR SOURCES</span>${icon('doc')}</div><h2>Start with a page.</h2><p class="muted">One document. A world of questions.</p>
        <button id="upload" class="upload">${icon('upload')}<strong>Drop your PDF here</strong><span>or click to browse files</span><small>PDF DOCUMENT</small></button><input id="file" type="file" accept="application/pdf,.pdf" hidden>
        <label class="field-label" for="document">ACTIVE DOCUMENT</label><select id="document"><option value="">Loading documents…</option></select>
        <div class="document-card"><span class="file-symbol">PDF</span><div><strong id="documentName">No document selected</strong><span id="documentDetail">Choose a source to begin</span></div></div>
        <div class="source-note"><span class="note-icon">↳</span><p><strong>Grounded in your document.</strong>Answers use extracted pages, with page references you can check.</p></div>
        <div class="starter"><span class="field-label">A GOOD PLACE TO START</span><p>“What are the key ideas<br>in this document?”</p><span>Start a session and ask out loud.</span></div>
        <button id="retry" class="text-button">↻ Refresh documents</button>
      </aside>
      <section class="conversation-column">
        <div class="voice-panel"><div class="voice-top"><span class="section-label">02 / VOICE ROOM</span><span id="sessionBadge" class="session-badge">○ STANDBY</span></div>
          <div class="voice-center"><div id="orb" class="orb"><div class="orbit orbit-one"></div><div class="orbit orbit-two"></div><div class="orb-core">${icon('mic')}</div></div><h2 id="status">Room for a question.</h2><p id="hint">Select a PDF, then make yourself heard.</p></div>
          <div class="voice-controls"><button id="mute" class="mute-button" aria-label="Mute microphone" aria-pressed="false" disabled>${icon('mic')}</button><button id="call" disabled>Start conversation ${icon('arrow')}</button><span id="timer" class="timer">00:00</span></div><div class="voice-foot"><span>Speak naturally. Interrupt anytime.</span><span id="voiceState">MIC OFF</span></div>
        </div>
        <div class="transcript-panel panel"><div class="panel-heading"><div><span class="section-label">THE CONVERSATION</span><h2>In your own words.</h2></div><span id="turnCount" class="count">0 turns</span></div><div id="transcript" class="transcript" role="log" aria-label="Conversation transcript" aria-live="polite"><div class="empty transcript-empty"><span class="empty-glyph">“</span><h3>Good questions start here.</h3><p>Your words and the agent’s replies<br>will appear as the conversation unfolds.</p></div></div><div id="partial" class="partial" aria-live="off"></div><div class="transcript-footer"><span class="status-dot"></span> Live transcript <span>Powered by your curiosity</span></div></div>
      </section>
      <section class="activity-panel panel"><div class="panel-heading"><div><span class="section-label">03 / BEHIND THE ANSWER</span><h2>Nothing behind a curtain.</h2></div><span id="activityCount" class="count">0</span></div><p class="activity-intro">Follow the tools, evidence, and connections as they happen.</p>
        <div class="agent-legend"><span><i class="voice-dot"></i> Voice agent</span><span><i class="graph-dot"></i> LangGraph worker</span></div>
        <div class="filters" role="group" aria-label="Filter agent activity"><button data-filter="all" class="selected" aria-pressed="true">All activity</button><button data-filter="voice" aria-pressed="false">Tool calls <span id="toolCount">0</span></button><button data-filter="graph" aria-pressed="false">Knowledge <span id="graphCount">0</span></button></div>
        <div id="activity" class="activity"><div class="empty activity-empty"><div class="flow-diagram"><span>${icon('mic')}</span><b>→</b><span>${icon('doc')}</span><b>→</b><span>${icon('graph')}</span></div><h3>From question to connection.</h3><p>Watch the voice agent find evidence and the background worker connect the dots.</p><div class="empty-steps"><span><b>01</b> Search your pages</span><span><b>02</b> Extract supported facts</span><span><b>03</b> Save relationships</span></div></div></div>
        <div class="activity-footer">REAL EXECUTION EVENTS <span>Expand any step to inspect ↗</span></div>
      </section>
    </div></div><section id="graphScreen" hidden aria-label="Knowledge atlas"></section><p id="message" class="message" role="status" aria-live="polite"></p>
  </main><footer><span class="footer-brand">margin</span><span>A little closer to understanding.</span><span>YOUR DOCUMENT. IN CONVERSATION.</span></footer>
</div>`;

let client, connected = false, busy = false, muted = false, documents = [], filter = 'all', startedAt = 0, timer;
let turns = [], events = new Map(), sessionDocument;
const audio = new Audio(); audio.autoplay = true;
const atlas = mountGraph($('#graphScreen'), {
  onConversation: () => switchScreen(false),
  onEnd: () => $('#call').click(),
  onMute: () => $('#mute').click(),
});
function switchScreen(graph) {
  $('#conversationScreen').hidden = graph;
  atlas.show(graph);
  $('#conversationTab').classList.toggle('active', !graph);
  $('#graphTab').classList.toggle('active', graph);
  $('#conversationTab').setAttribute('aria-current', graph ? 'false' : 'page');
  $('#graphTab').setAttribute('aria-current', graph ? 'page' : 'false');
}
$('#conversationTab').onclick = () => switchScreen(false);
$('#graphTab').onclick = () => switchScreen(true);
const showMessage = text => { $('#message').textContent = text || ''; };
const activityReceiver = createActivityReceiver(event => {
  if (event?.type === 'assistant-turn') addTranscript('assistant', event.text, event.interrupted);
  if (event?.type === 'agent-activity') receiveActivity(event);
}, showMessage);
const errorMessage = error => typeof error === 'string' ? error : error?.message || error?.detail || error?.error || 'An unexpected error occurred.';
function setStatus(title, subtitle, mode = '') {
  atlas.updateVoice(connected, title, muted);
  $('#status').textContent = title; $('#hint').textContent = subtitle; $('#orb').className = `orb ${mode}`;
  $('#voiceState').textContent = connected ? (muted ? 'MIC MUTED' : mode === 'speaking' ? 'AGENT SPEAKING' : 'MIC ON') : 'MIC OFF';
}
function addTranscript(role, text, interrupted = false) {
  if (!text?.trim()) return;
  turns.push({role, text, interrupted, timestamp: new Date().toISOString()});
  $('#transcript').querySelector('.empty')?.remove();
  const item = document.createElement('article'); item.className = `utterance ${role}`;
  item.innerHTML = `<div class="utterance-meta"><span class="avatar">${role === 'user' ? 'Y' : 'm·'}</span><strong>${role === 'user' ? 'You' : 'Margin'}</strong><time>${new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}</time>${interrupted ? '<small>Interrupted</small>' : ''}</div><p>${escape(text)}</p>`;
  const el = $('#transcript'); const follow = el.scrollHeight - el.scrollTop - el.clientHeight < 90;
  el.append(item); if (follow) el.scrollTop = el.scrollHeight;
  $('#turnCount').textContent = `${turns.length} turns`;
}
function renderActivity() {
  const host = $('#activity');
  if (!events.size) return;
  const open = new Set([...host.querySelectorAll('details[open]')].map(e => e.dataset.id));
  const items = [...events.values()].filter(e => filter === 'all' || e.agent === filter);
  host.innerHTML = items.length ? items.map(event => {
    const graph = event.agent === 'graph';
    const facts = event.output?.claims?.map(c => ({subject:c.subject.name,relation:c.relation,object:c.object.name,evidence:c.evidence.map(e=>e.quote).join(' / '),page_number:c.evidence.map(e=>e.page_number).join(', ')})) || event.output?.facts;
    const readable = facts?.length ? `<div class="facts">${facts.map(f => `<div class="fact"><div><strong>${escape(f.subject)}</strong><span>${escape(f.relation)} →</span><strong>${escape(f.object)}</strong></div><blockquote>${escape(f.evidence)}</blockquote><small>PAGE ${escape(f.page_number)}</small></div>`).join('')}</div>` : '';
    const descriptions = {context:'Read retrieved pages and surrounding context',interpret:'Resolve the inquiry and its topic',validate:'Review relationships against source evidence',search_document:'Find evidence in the document',get_page:'Read the complete page',extract:'Extract evidence-backed relationships',persist:'Save relationships to the knowledge graph'};
    return `<details class="event ${graph ? 'graph' : 'voice'}" data-id="${escape(event.id)}" ${open.has(event.id) ? 'open' : ''}><summary><span class="event-icon">${icon(graph ? 'graph' : 'doc')}</span><div class="event-summary"><div class="event-agent">${graph ? 'LANGGRAPH WORKER' : 'VOICE AGENT'}<time>${new Date(event.timestamp).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'})}</time></div><strong>${escape(event.name)}</strong><p>${descriptions[event.name] || 'Agent execution step'}</p><span class="event-status ${escape(event.status)}">${event.status === 'running' ? '◌' : event.status === 'completed' ? '✓' : '•'} ${escape(event.status)}${event.duration_ms != null ? ` <span>· ${(event.duration_ms / 1000).toFixed(2)}s</span>` : ''}</span></div><span class="chevron">⌄</span></summary><div class="event-detail">${readable}<div class="payloads"><section><h4>ARGUMENTS</h4><pre>${escape(json(event.arguments))}</pre></section><section><h4>OUTPUT</h4><pre>${escape(event.output === undefined ? event.status === 'running' ? 'Waiting for output…' : 'No output returned.' : json(event.output))}</pre></section></div>${event.question_id ? `<div class="event-id">Question ${escape(event.question_id)}</div>` : ''}</div></details>`;
  }).join('') : '<div class="empty"><h3>No steps here yet.</h3><p>Activity for this agent will appear here.</p></div>';
  $('#activityCount').textContent = events.size;
  $('#toolCount').textContent = [...events.values()].filter(e => e.agent === 'voice').length;
  $('#graphCount').textContent = [...events.values()].filter(e => e.agent === 'graph').length;
}
function receiveActivity(event) { events.set(event.id, {...events.get(event.id), ...event}); renderActivity(); if (event.agent === 'graph' && event.name === 'persist' && event.status === 'completed') atlas.refresh(); }
function updateSelection() {
  const doc = documents.find(d => d.id === $('#document').value);
  atlas.setDocument(doc);
  $('#documentName').textContent = doc?.title || doc?.filename || 'No document selected';
  $('#documentDetail').textContent = doc ? `${doc.page_count} pages · Ready to explore` : 'Choose a source to begin';
  $('#call').disabled = busy || (!connected && !doc);
  $('#document').disabled = connected || busy; $('#upload').disabled = connected || busy; $('#file').disabled = connected || busy; $('#retry').disabled = connected || busy;
}
async function loadDocuments(selected = $('#document').value) {
  const response = await fetch('/documents');
  if (!response.ok) throw new Error('Document service unavailable. Start the voice service, then refresh documents.');
  documents = await response.json();
  $('#document').replaceChildren(new Option(documents.length ? 'Select a document' : 'Upload your first PDF', ''));
  documents.forEach(doc => $('#document').add(new Option(doc.title || doc.filename, doc.id)));
  $('#document').value = selected; updateSelection();
}
async function uploadFile(file) {
  if (!file || busy || connected) return;
  if (!/\.pdf$/i.test(file.name)) { showMessage('Please choose a PDF document.'); return; }
  busy = true; updateSelection(); showMessage('Extracting your PDF. This may take a moment…'); $('#upload').classList.add('loading');
  try {
    const form = new FormData(); form.append('file', file);
    const response = await fetch('/api/documents', {method:'POST',body:form}); const result = await response.json();
    if (!response.ok) throw new Error(result.detail || 'Upload failed. Please try again.');
    await loadDocuments(result.id); showMessage(`${result.page_count} pages extracted. Your document is ready.`);
  } catch (error) { showMessage(errorMessage(error)); }
  finally { busy = false; updateSelection(); $('#file').value = ''; $('#upload').classList.remove('loading'); }
}
$('#document').addEventListener('change', updateSelection);
$('#upload').addEventListener('click', () => $('#file').click());
$('#file').addEventListener('change', () => uploadFile($('#file').files?.[0]));
$('#upload').addEventListener('dragover', event => { event.preventDefault(); $('#upload').classList.add('dragover'); });
$('#upload').addEventListener('dragleave', () => $('#upload').classList.remove('dragover'));
$('#upload').addEventListener('drop', event => { event.preventDefault(); $('#upload').classList.remove('dragover'); uploadFile(event.dataTransfer.files[0]); });
$('#retry').addEventListener('click', () => loadDocuments().then(() => showMessage('Documents refreshed.')).catch(e => showMessage(errorMessage(e))));
$('.filters').addEventListener('click', event => {
  const button = event.target.closest('[data-filter]'); if (!button) return;
  filter = button.dataset.filter;
  document.querySelectorAll('[data-filter]').forEach(el => { el.classList.toggle('selected', el === button); el.setAttribute('aria-pressed', String(el === button)); }); renderActivity();
});
$('#export').addEventListener('click', () => {
  const blob = new Blob([json({document:sessionDocument || documents.find(d => d.id === $('#document').value),transcript:turns,activity:[...events.values()]})], {type:'application/json'});
  const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'margin-session.json'; link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 1000);
});
$('#mute').addEventListener('click', () => { if (!connected) return; muted = !muted; client.enableMic(!muted); $('#mute').setAttribute('aria-pressed', String(muted)); $('#mute').setAttribute('aria-label', muted ? 'Unmute microphone' : 'Mute microphone'); $('#voiceState').textContent = muted ? 'MIC MUTED' : 'MIC ON'; atlas.updateVoice(connected, $('#status').textContent, muted); });
function disconnectState() {
  connected = false; busy = false; muted = false; clearInterval(timer);
  $('#call').innerHTML = `Start conversation ${icon('arrow')}`; $('#call').classList.remove('end-call'); $('#mute').disabled = true; $('#mute').setAttribute('aria-pressed','false'); $('#mute').setAttribute('aria-label','Mute microphone'); $('#partial').textContent = ''; $('#sessionBadge').textContent = '○ STANDBY';
  audio.srcObject = null; setStatus('Room for a question.', 'Your next question is a conversation away.');
  for (const [id, event] of events) if (event.status === 'running') events.set(id, {...event, status:'disconnected'});
  renderActivity(); updateSelection();
}
$('#call').addEventListener('click', async () => {
  if (busy) return;
  if (connected) { busy = true; updateSelection(); try { await client.disconnect(); } catch (e) { showMessage(errorMessage(e)); } finally { disconnectState(); } return; }
  if (!$('#document').value) return;
  busy = true; updateSelection(); showMessage(''); setStatus('Making a connection.', 'Allow microphone access when prompted.', 'connecting');
  // A new session has its own transcript and activity history.
  sessionDocument = documents.find(d => d.id === $('#document').value);
  activityReceiver.reset();
  turns = []; events.clear(); $('#transcript').replaceChildren(); $('#activity').innerHTML = '<div class="empty"><h3>Ready to follow along.</h3><p>Agent activity will appear when you ask a question.</p></div>'; $('#turnCount').textContent = '0 turns'; $('#activityCount').textContent = '0'; $('#toolCount').textContent = '0'; $('#graphCount').textContent = '0';
  client = new PipecatClient({transport:new SmallWebRTCTransport(),enableMic:true,enableCam:false, callbacks:{
    onConnected: () => { connected = true; busy = false; startedAt = Date.now(); $('#timer').textContent = '00:00'; timer = setInterval(() => { const seconds = Math.floor((Date.now()-startedAt)/1000); $('#timer').textContent = `${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`; },1000); $('#mute').disabled = false; $('#call').innerHTML = 'End conversation <span>×</span>'; $('#call').classList.add('end-call'); $('#sessionBadge').textContent = '● LIVE SESSION'; setStatus('I’m listening.', 'Ask about anything in your document.', 'listening'); updateSelection(); },
    onDisconnected: disconnectState,
    onUserStartedSpeaking: () => setStatus('I’m listening.', 'Take your time. There’s room for every question.', 'listening'),
    onUserStoppedSpeaking: () => setStatus('Finding the thread.', 'Following your question into the document.', 'thinking'),
    onBotStartedSpeaking: () => setStatus('Here’s what I found.', 'You can interrupt at any time.', 'speaking'),
    onBotStoppedSpeaking: () => setStatus('Where to next?', 'Ask a follow-up. Keep the conversation going.', 'listening'),
    onUserTranscript: event => { $('#partial').textContent = event.final ? '' : event.text; if (event.final) addTranscript('user',event.text); },
    onServerMessage: message => { const event = message?.type === 'server-message' ? message.data : message; activityReceiver.receive(event); },
    onError: error => showMessage(errorMessage(error)), onDeviceError: error => showMessage(errorMessage(error)),
  }});
  client.on(RTVIEvent.TrackStarted, (track, participant) => { if (track.kind === 'audio' && !participant?.local) { audio.srcObject = new MediaStream([track]); audio.play().catch(() => showMessage('Allow audio playback in your browser.')); } });
  try { await client.startBotAndConnect({endpoint:'/start',requestData:{transport:'webrtc',createDailyRoom:false,enableDefaultIceServers:true,body:{document_id:$('#document').value}}}); }
  catch (error) { showMessage(errorMessage(error)); try { await client.disconnect(); } catch {} disconnectState(); }
});
loadDocuments().catch(error => showMessage(errorMessage(error)));
