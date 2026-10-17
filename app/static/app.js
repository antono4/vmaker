/* MiniMax H3 Video Maker - studio UI */
'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const state = {
  modes: {},
  modeOrder: [],
  mode: 't2v',
  backends: [],
  backend: 'demo',
  shots: [],
  refs: [],
  jobs: [],
  selected: null,
  polling: null,
  busy: false,
};

/* ---------------------------------------------------------------- utils */
function toast(message, kind = '') {
  const el = $('#toast');
  el.textContent = message;
  el.className = `toast show ${kind}`;
  clearTimeout(el._timer);
  el._timer = setTimeout(() => (el.className = 'toast'), 4200);
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const text = await response.text();
  let body = {};
  try { body = text ? JSON.parse(text) : {}; } catch { body = { detail: text }; }
  if (!response.ok) {
    const hint = body.hint ? ` (${body.hint})` : '';
    throw new Error((body.detail || `HTTP ${response.status}`) + hint);
  }
  return body;
}

function fmtTime(seconds) {
  const s = Number(seconds) || 0;
  const m = Math.floor(s / 60);
  const r = Math.round(s % 60);
  return `${m}:${String(r).padStart(2, '0')}`;
}

/* ------------------------------------------------------------- bootstrap */
async function boot() {
  bindStaticEvents();
  await Promise.all([loadModes(), loadBackends()]);
  addShot(true);
  renderAll();
  await refreshJobs();
  startPolling();
  checkHealth();
  setInterval(checkHealth, 30000);
}

async function checkHealth() {
  const pill = $('#health-pill');
  try {
    const body = await api('/healthz');
    pill.className = 'pill ok';
    $('#health-text').textContent = `online · v${body.version}`;
    $('#foot-note').textContent = body.encoder
      ? 'ffmpeg ready'
      : 'no ffmpeg found - video encoding will fail';
  } catch (err) {
    pill.className = 'pill bad';
    $('#health-text').textContent = 'offline';
  }
}

async function loadModes() {
  const body = await api('/api/modes');
  state.modes = {};
  state.modeOrder = [];
  for (const mode of body.modes) {
    state.modes[mode.key] = mode;
    state.modeOrder.push(mode.key);
  }
  state.shotSizes = body.shot_sizes || [];
  state.cameraMoves = body.camera_moves || [];
  state.retention = body.retention_policies || [];
  state.model = body.model || {};
}

async function loadBackends() {
  const body = await api('/api/backends');
  state.backends = body.backends || [];
  const preferred = state.backends.find((b) => b.name === body.default && b.available)
    || state.backends.find((b) => b.available)
    || state.backends[0];
  state.backend = preferred ? preferred.name : 'demo';
  renderBackends();
}

/* ------------------------------------------------------------ rendering */
function renderAll() {
  renderModeTabs();
  renderModeNote();
  renderShots();
  renderRefs();
  renderBackends();
  renderAspectOptions();
  updatePromptPreview();
}

function renderModeTabs() {
  const host = $('#mode-tabs');
  host.innerHTML = state.modeOrder.map((key) => {
    const mode = state.modes[key];
    const limits = mode.limits;
    const bits = [];
    if (limits.images) bits.push(`${limits.images} img`);
    if (limits.videos) bits.push(`${limits.videos} vid`);
    if (limits.audio) bits.push(`${limits.audio} aud`);
    return `<button class="mode ${key === state.mode ? 'active' : ''}" data-mode="${key}">
      <strong>${esc(mode.label)}</strong>
      <small>${esc(mode.task)}${bits.length ? ' · ' + bits.join(' · ') : ' · prompt only'}</small>
    </button>`;
  }).join('');
  $$('.mode', host).forEach((btn) => {
    btn.onclick = () => {
      state.mode = btn.dataset.mode;
      const mode = state.modes[state.mode];
      state.refs = [];
      renderAll();
      $('#f-duration').min = mode.duration.min;
      $('#f-duration').max = mode.duration.max;
      if (+$('#f-duration').value < mode.duration.min || +$('#f-duration').value > mode.duration.max) {
        $('#f-duration').value = mode.duration.default;
      }
      $('#out-duration').textContent = `${$('#f-duration').value}s`;
    };
  });
}

function renderModeNote() {
  const mode = state.modes[state.mode];
  if (!mode) return;
  $('#mode-note').textContent = mode.description;
}

function renderAspectOptions() {
  const mode = state.modes[state.mode];
  const select = $('#f-aspect');
  const current = select.value;
  select.innerHTML = mode.aspect_ratios
    .map((r) => `<option value="${r}">${r === 'auto' ? 'auto (from image)' : r}</option>`)
    .join('');
  select.value = mode.aspect_ratios.includes(current) ? current : mode.default_aspect;
}

function renderBackends() {
  const host = $('#backends');
  host.innerHTML = state.backends.map((b) => {
    const keyForm = b.accepts_key ? `
      <div class="key-form">
        <div class="key-row">
          <input type="password" class="key-input" data-key-for="${b.name}"
                 placeholder="Paste MiniMax API key (sk-...)" autocomplete="off"
                 value="" />
          <button class="btn tiny" data-key-save="${b.name}">Save key</button>
          ${b.key_source === 'session' ? `<button class="btn tiny ghost" data-key-clear="${b.name}">Forget</button>` : ''}
        </div>
        <input class="key-input base-input" data-base-for="${b.name}"
               placeholder="https://api.minimax.io (global) or https://api.minimaxi.com"
               value="" autocomplete="off" />
        <p class="key-note">${b.key_source === 'environment'
          ? 'A key is already set from the environment. A pasted key overrides it for this session only.'
          : 'Held in memory for this session only. Never written to disk.'}</p>
      </div>` : '';
    return `
    <div class="backend ${b.name === state.backend ? 'active' : ''} ${b.available ? '' : 'unavailable'}">
      <label class="b-pick">
        <input type="radio" name="backend" value="${b.name}" ${b.name === state.backend ? 'checked' : ''} />
        <div class="b-body">
          <div class="b-top">
            <strong>${esc(b.label)}</strong>
            <span class="tag ${b.available ? 'ok' : 'bad'}">${b.available ? 'ready' : 'not ready'}</span>
          </div>
          <p>${esc(b.reason || b.description)}</p>
        </div>
      </label>
      ${keyForm}
    </div>`;
  }).join('');
  $$('input[name=backend]', host).forEach((input) => {
    input.onchange = () => {
      state.backend = input.value;
      renderBackends();
    };
  });
  $$('[data-key-save]', host).forEach((btn) => {
    btn.onclick = async (event) => {
      event.preventDefault();
      const name = btn.dataset.keySave;
      const key = $(`[data-key-for="${name}"]`, host).value.trim();
      const base = $(`[data-base-for="${name}"]`, host).value.trim();
      if (!key && !base) {
        toast('Enter an API key first.', 'error');
        return;
      }
      btn.disabled = true;
      try {
        const body = await api(`/api/backends/${name}/key`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ api_key: key, api_base: base }),
        });
        state.backends = state.backends.map((b) => (b.name === name ? body.backend : b));
        if (body.available && !state.backends.find((b) => b.name === state.backend && b.available)) {
          state.backend = name;
        }
        renderBackends();
        toast(body.available ? 'API key saved for this session.' : body.reason, body.available ? 'ok' : 'error');
      } catch (err) {
        toast(err.message, 'error');
        btn.disabled = false;
      }
    };
  });
  $$('[data-key-clear]', host).forEach((btn) => {
    btn.onclick = async (event) => {
      event.preventDefault();
      const name = btn.dataset.keyClear;
      try {
        const body = await api(`/api/backends/${name}/key`, { method: 'DELETE' });
        state.backends = state.backends.map((b) => (b.name === name ? body.backend : b));
        renderBackends();
        toast('API key cleared.', 'ok');
      } catch (err) {
        toast(err.message, 'error');
      }
    };
  });
}

function renderShots() {
  const host = $('#shots');
  host.innerHTML = state.shots.map((shot, i) => `
    <div class="card" data-index="${i}">
      <div class="card-head">
        <strong>Shot ${i + 1}</strong>
        <button class="btn tiny danger" data-remove-shot="${i}" ${state.shots.length < 2 ? 'disabled' : ''}>Remove</button>
      </div>
      <div class="grid two">
        <label class="field"><span>Start at (s)</span>
          <input type="number" step="0.1" min="0" data-shot="${i}" data-key="start_seconds"
                 value="${shot.start_seconds ?? ''}" placeholder="${i === 0 ? '0' : 'auto'}" /></label>
        <label class="field"><span>Shot size</span>
          <select data-shot="${i}" data-key="shot_size">
            <option value="">-</option>
            ${(state.shotSizes || []).map((s) => `<option ${shot.shot_size === s ? 'selected' : ''}>${s}</option>`).join('')}
          </select></label>
        <label class="field"><span>Camera move</span>
          <select data-shot="${i}" data-key="camera_move">
            <option value="">-</option>
            ${(state.cameraMoves || []).map((s) => `<option ${shot.camera_move === s ? 'selected' : ''}>${s}</option>`).join('')}
          </select></label>
        <label class="field"><span>Amplitude</span>
          <input data-shot="${i}" data-key="amplitude" value="${esc(shot.amplitude || '')}" placeholder="subtle / moderate / strong" /></label>
        <label class="field"><span>Speed</span>
          <input data-shot="${i}" data-key="speed" value="${esc(shot.speed || '')}" placeholder="slow / steady / fast" /></label>
        <label class="field wide"><span>Shot description</span>
          <textarea rows="3" data-shot="${i}" data-key="description"
            placeholder="Describe what happens, in timeline order.">${esc(shot.description || '')}</textarea></label>
        <label class="field wide"><span>Dialogue <small>one line per utterance, &lt;d&gt;[lang] text&lt;/d&gt;</small></span>
          <textarea rows="2" data-shot="${i}" data-key="dialogue"
            placeholder="<d>[English] Follow the wind, live free.</d>">${esc((shot.dialogue || []).join('\n'))}</textarea></label>
        <label class="field wide"><span>On-screen text <small>one per line</small></span>
          <textarea rows="2" data-shot="${i}" data-key="on_screen_text"
            placeholder="OPEN 24 HOURS">${esc((shot.on_screen_text || []).join('\n'))}</textarea></label>
      </div>
    </div>`).join('');

  $$('[data-remove-shot]', host).forEach((btn) => {
    btn.onclick = () => {
      state.shots.splice(+btn.dataset.removeShot, 1);
      renderShots();
      updatePromptPreview();
    };
  });
  $$('[data-shot]', host).forEach((input) => {
    input.oninput = input.onchange = () => {
      const index = +input.dataset.shot;
      const key = input.dataset.key;
      let value = input.value;
      if (key === 'dialogue' || key === 'on_screen_text') {
        value = value.split('\n').filter((l) => l.trim());
      }
      if (key === 'start_seconds') value = value === '' ? null : Number(value);
      state.shots[index][key] = value;
      updatePromptPreview();
    };
  });
  $('#shot-count').textContent = state.shots.length;
}

function renderRefs() {
  const mode = state.modes[state.mode];
  const host = $('#refs');
  const limits = mode.limits;
  $('#ref-limits').textContent = [
    `${limits.images} image(s)`, `${limits.videos} video(s)`, `${limits.audio} audio clip(s)`,
    limits.max_total_files ? `max ${limits.max_total_files} files total` : '',
  ].filter(Boolean).join(' · ');

  if (!limits.images && !limits.videos && !limits.audio) {
    host.innerHTML = '<p class="empty-note">Text-to-video needs no reference files.</p>';
    $('#ref-count').textContent = 0;
    return;
  }

  host.innerHTML = state.refs.map((ref, i) => {
    const preview = ref.preview
      ? (ref.kind === 'image'
        ? `<img src="${esc(ref.preview)}" alt="" style="max-height:74px;border-radius:6px;border:1px solid var(--line)" />`
        : `<span class="tag">${esc(ref.filename || 'file selected')}</span>`)
      : '<span class="tag">no file</span>';
    const labelOptions = ['Picture', 'Video', 'Audio', 'Subject']
      .map((l) => `<option value="${l}" ${(ref.label || '').startsWith(l) ? 'selected' : ''}>${l}</option>`).join('');
    return `
    <div class="card" data-ref="${i}">
      <div class="card-head">
        <strong>${esc(ref.kind)} reference</strong>
        <button class="btn tiny danger" data-remove-ref="${i}">Remove</button>
      </div>
      <div class="grid two">
        <label class="field"><span>Type</span>
          <select data-ref="${i}" data-key="kind">
            ${['image', 'video', 'audio'].map((k) => `<option value="${k}" ${ref.kind === k ? 'selected' : ''}>${k}</option>`).join('')}
          </select></label>
        <label class="field"><span>Label</span>
          <div style="display:flex;gap:6px">
            <select data-ref="${i}" data-key="labelPrefix" style="max-width:110px">${labelOptions}</select>
            <input data-ref="${i}" data-key="labelNumber" type="number" min="1" value="${esc(ref.labelNumber || i + 1)}" />
          </div></label>
        <label class="field wide"><span>Public URL <small>required by the MiniMax API backend</small></span>
          <input data-ref="${i}" data-key="uri" value="${esc(ref.uri || '')}" placeholder="https://.../reference.png" /></label>
        <label class="field wide"><span>Description used in subject_definitions / retention_analysis</span>
          <input data-ref="${i}" data-key="description" value="${esc(ref.description || '')}"
                 placeholder="the young man with short wavy blonde hair wearing a bright pink suit" /></label>
        <label class="field"><span>Retention policy</span>
          <select data-ref="${i}" data-key="retention">
            ${(state.retention || []).map((r) => `<option ${ref.retention === r ? 'selected' : ''}>${r}</option>`).join('')}
          </select></label>
        <label class="field"><span>Local file <small>uploaded on generate</small></span>
          <input type="file" data-ref="${i}" data-key="file" /></label>
      </div>
      <div style="margin-top:8px">${preview}</div>
    </div>`;
  }).join('');

  $$('[data-remove-ref]', host).forEach((btn) => {
    btn.onclick = () => {
      state.refs.splice(+btn.dataset.removeRef, 1);
      renderRefs();
      updatePromptPreview();
    };
  });
  $$('[data-ref]', host).forEach((input) => {
    const index = +input.dataset.ref;
    const key = input.dataset.key;
    const handler = () => {
      const ref = state.refs[index];
      if (key === 'file') {
        const file = input.files && input.files[0];
        if (!file) return;
        ref.file = file;
        ref.filename = file.name;
        if (file.type.startsWith('image/')) ref.preview = URL.createObjectURL(file);
        if (!ref.description) ref.description = `the content of ${file.name}`;
        renderRefs();
      } else if (key === 'labelPrefix' || key === 'labelNumber') {
        ref[key] = input.value;
        ref.label = `<${ref.labelPrefix || 'Picture'} ${ref.labelNumber || index + 1}>`;
      } else if (key === 'kind') {
        ref.kind = input.value;
        if (!ref.labelPrefix) ref.labelPrefix = { image: 'Picture', video: 'Video', audio: 'Audio' }[ref.kind];
        ref.label = `<${ref.labelPrefix} ${ref.labelNumber || index + 1}>`;
        renderRefs();
      } else {
        ref[key] = input.value;
      }
      updatePromptPreview();
    };
    input.oninput = input.onchange = handler;
  });
  $('#ref-count').textContent = state.refs.length;
}

/* ------------------------------------------------------------ composer */
function addShot(initial = false) {
  state.shots.push({
    description: '', shot_size: '', camera_move: '', amplitude: '', speed: '',
    start_seconds: initial ? 0 : null, dialogue: [], on_screen_text: [],
  });
  if (!initial) { renderShots(); }
  updatePromptPreview();
}

function addRef(kind = 'image') {
  const mode = state.modes[state.mode];
  const used = state.refs.filter((r) => r.kind === kind).length;
  const limit = { image: mode.limits.images, video: mode.limits.videos, audio: mode.limits.audio }[kind];
  if (used >= limit) {
    toast(`No ${kind} slots left for ${mode.label}.`, 'error');
    return;
  }
  state.refs.push({
    kind, labelPrefix: { image: 'Picture', video: 'Video', audio: 'Audio' }[kind],
    labelNumber: used + 1, label: `<${ { image: 'Picture', video: 'Video', audio: 'Audio' }[kind]} ${used + 1}>`,
    description: '', retention: 'fully_preserved', uri: '', filename: '', file: null, preview: '',
  });
  renderRefs();
  updatePromptPreview();
}

function specPayload() {
  return {
    mode: state.mode,
    style: $('#f-style').value,
    setting: $('#f-setting').value,
    lighting: $('#f-lighting').value,
    subject: $('#f-subject').value,
    action: $('#f-action').value,
    soundscape: $('#f-soundscape').value,
    music: $('#f-music').value,
    negative: $('#f-negative').value,
    language: $('#f-language').value,
    shots: state.shots,
    references: state.refs.map((r) => ({
      kind: r.kind, label: r.label || '', description: r.description || '',
      retention: r.retention || 'reference', uri: r.uri || '', filename: r.filename || '',
    })),
  };
}

let previewTimer = null;
function updatePromptPreview() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(async () => {
    try {
      const body = await api('/api/prompt/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(specPayload()),
      });
      $('#prompt-preview').textContent = body.prompt || '(empty)';
      $('#prompt-chars').textContent = `${body.characters} chars`;
      $('#prompt-problems').innerHTML = (body.problems || []).map((p) => `<li>${esc(p)}</li>`).join('');
    } catch (err) {
      $('#prompt-preview').textContent = `Preview error: ${err.message}`;
    }
  }, 220);
}

/* ------------------------------------------------------------ generate */
async function generate() {
  if (state.busy) return;
  const raw = $('#f-raw').value.trim();
  const payload = {
    ...specPayload(),
    backend: state.backend,
    duration: Number($('#f-duration').value),
    aspect_ratio: $('#f-aspect').value,
    resolution: $('#f-resolution').value,
    seed: Number($('#f-seed').value) || 0,
    steps: Number($('#f-steps').value) || 0,
    raw_prompt: raw,
  };

  const form = new FormData();
  form.append('payload', JSON.stringify(payload));
  state.refs.forEach((ref, i) => {
    if (ref.file) form.append(`file_${i}`, ref.file, ref.file.name);
  });

  state.busy = true;
  const btn = $('#btn-generate');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Generating…';
  try {
    const body = await api('/api/generate', { method: 'POST', body: form });
    state.selected = body.job.id;
    toast('Job queued.', 'ok');
    await refreshJobs();
    renderPlayer(store(state.selected));
    startPolling();
  } catch (err) {
    toast(err.message, 'error');
  } finally {
    state.busy = false;
    btn.disabled = false;
    btn.textContent = 'Generate video';
  }
}

/* ----------------------------------------------------------------- jobs */
function store(id) { return state.jobs.find((j) => j.id === id); }

async function refreshJobs() {
  try {
    const body = await api('/api/jobs');
    state.jobs = body.jobs || [];
    renderGallery();
    if (state.selected) renderPlayer(store(state.selected));
  } catch (err) { /* keep the previous list */ }
}

function startPolling() {
  if (state.polling) return;
  state.polling = setInterval(async () => {
    const active = state.jobs.some((j) => j.status === 'running' || j.status === 'queued');
    if (!active) return;
    await refreshJobs();
  }, 2000);
}

function renderGallery() {
  $('#job-count').textContent = state.jobs.length;
  const host = $('#gallery');
  if (!state.jobs.length) {
    host.innerHTML = '<p class="empty-note">No renders yet.</p>';
    return;
  }
  host.innerHTML = state.jobs.map((job) => `
    <div class="tile ${job.id === state.selected ? 'active' : ''}" data-job="${job.id}">
      <div class="thumb">
        ${job.poster_url ? `<img src="${esc(job.poster_url)}" alt="" />` : '<span class="ph">no preview</span>'}
      </div>
      <div class="tile-body">
        <p title="${esc(job.prompt)}">${esc(job.prompt.slice(0, 90))}</p>
        <div class="row">
          <span class="badge ${esc(job.status)}">${esc(job.status)}</span>
          <span class="mono" style="font-size:10.5px;color:var(--dim)">${esc(job.mode)} · ${job.duration}s</span>
        </div>
        <div class="tile-actions">
          ${job.video_url ? `<a class="btn tiny" href="${esc(job.video_url)}" download>Download</a>` : ''}
          <button class="btn tiny danger" data-del="${job.id}">${job.status === 'running' || job.status === 'queued' ? 'Cancel' : 'Delete'}</button>
        </div>
      </div>
    </div>`).join('');

  $$('[data-job]', host).forEach((tile) => {
    tile.onclick = (event) => {
      if (event.target.closest('button, a')) return;
      state.selected = tile.dataset.job;
      renderGallery();
      renderPlayer(store(state.selected));
    };
  });
  $$('[data-del]', host).forEach((btn) => {
    btn.onclick = async (event) => {
      event.stopPropagation();
      try {
        await api(`/api/jobs/${btn.dataset.del}`, { method: 'DELETE' });
        if (state.selected === btn.dataset.del) { state.selected = null; renderPlayer(null); }
        await refreshJobs();
      } catch (err) { toast(err.message, 'error'); }
    };
  });
}

function renderPlayer(job) {
  const host = $('#player');
  if (!job) {
    host.className = 'player empty';
    host.innerHTML = '<div class="player-empty">Your render appears here.</div>';
    $('#output-hint').textContent = 'nothing rendered yet';
    return;
  }
  $('#output-hint').textContent = `${job.status}${job.stage ? ' · ' + job.stage : ''}`;
  host.className = 'player';
  const meta = job.meta || {};
  const bits = [
    `mode ${job.mode}`, `task ${job.task}`, `backend ${job.backend}`,
    `${job.duration}s`, job.aspect_ratio, job.resolution,
    `seed ${job.seed}`,
    meta.render_seconds ? `rendered in ${meta.render_seconds}s` : '',
    meta.watermarked ? 'watermarked demo' : '',
  ].filter(Boolean);

  if (job.status === 'completed' && job.video_url) {
    host.innerHTML = `
      <video src="${esc(job.video_url)}" controls autoplay loop muted playsinline poster="${esc(job.poster_url || '')}"></video>
      <div class="player-meta">
        ${bits.map((b) => `<span class="tag">${esc(b)}</span>`).join('')}
        <a class="btn tiny" href="${esc(job.video_url)}" download>Download mp4</a>
        <button class="btn tiny" id="btn-2k">Regenerate 2K (API)</button>
      </div>`;
    const twoK = $('#btn-2k');
    if (twoK) {
      twoK.onclick = async () => {
        twoK.disabled = true;
        twoK.innerHTML = '<span class="spinner"></span> 2K…';
        try {
          const body = await api(`/api/jobs/${job.id}/regenerate-2k`, { method: 'POST' });
          state.jobs = state.jobs.map((j) => (j.id === body.job.id ? body.job : j));
          renderGallery();
          renderPlayer(body.job);
          toast('2K regeneration complete.', 'ok');
        } catch (err) {
          toast(err.message, 'error');
          twoK.disabled = false;
          twoK.textContent = 'Regenerate 2K (API)';
        }
      };
    }
    return;
  }

  if (job.status === 'failed') {
    host.innerHTML = `
      <div class="player-empty" style="padding:20px;text-align:center">
        <div style="color:var(--danger);margin-bottom:6px">Render failed</div>
        <div class="mono" style="font-size:11.5px;max-width:560px">${esc(job.error || 'unknown error')}</div>
        ${meta.hint ? `<div style="margin-top:8px;color:var(--muted);font-size:12px">${esc(meta.hint)}</div>` : ''}
      </div>`;
    return;
  }

  host.innerHTML = `
    <div class="player-empty" style="width:100%">
      <div style="text-align:center;padding:20px">
        <div><span class="spinner"></span> ${esc(job.stage || job.status)}</div>
        <div style="color:var(--dim);font-size:11.5px;margin-top:6px">${Math.round((job.progress || 0) * 100)}%</div>
      </div>
      <div class="progress-track"><div class="progress-bar" style="width:${Math.round((job.progress || 0) * 100)}%"></div></div>
    </div>`;
}

/* --------------------------------------------------------------- events */
function bindStaticEvents() {
  $('#btn-add-shot').onclick = () => addShot();
  $('#btn-refresh').onclick = () => { refreshJobs(); checkHealth(); };
  $('#btn-generate').onclick = generate;

  $('#btn-add-ref').onclick = () => {
    const mode = state.modes[state.mode];
    const kind = mode.limits.images ? 'image' : (mode.limits.videos ? 'video' : 'audio');
    addRef(kind);
  };

  ['#f-style', '#f-setting', '#f-lighting', '#f-subject', '#f-action',
   '#f-soundscape', '#f-music', '#f-negative', '#f-language']
    .forEach((sel) => { $(sel).oninput = updatePromptPreview; });

  $('#f-duration').oninput = (e) => {
    $('#out-duration').textContent = `${e.target.value}s`;
  };

  $('#btn-copy').onclick = async () => {
    const text = $('#prompt-preview').textContent;
    try {
      await navigator.clipboard.writeText(text);
      toast('Prompt copied.', 'ok');
    } catch {
      toast('Clipboard blocked by the browser.', 'error');
    }
  };

  $('#btn-expand').onclick = async () => {
    const text = $('#f-raw').value.trim() || $('#prompt-preview').textContent;
    const btn = $('#btn-expand');
    btn.disabled = true;
    try {
      const body = await api('/api/prompt/expand', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          duration: Number($('#f-duration').value),
          aspect_ratio: $('#f-aspect').value,
        }),
      });
      $('#f-raw').value = body.prompt;
      toast('Expanded with H3-Context-IR.', 'ok');
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  };
}

boot().catch((err) => {
  console.error(err);
  toast(`Startup failed: ${err.message}`, 'error');
});
