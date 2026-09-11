/* ================================================================
   voice.js — Offline voice agent for Crop Sathi

   The conversation itself lives on the server (backend/voice/): this
   file only captures speech, plays replies, and mirrors the dialogue
   on screen. It never decides what to say.

   Speech path, chosen automatically at startup by /voice/status:
     server mode   Vosk + Piper on the backend — works with no internet
     browser mode  Web Speech API fallback, used when the offline
                   models have not been downloaded yet

   Audio is captured as raw PCM through Web Audio and encoded to WAV
   here, because MediaRecorder produces webm/opus which the backend's
   `wave` reader cannot open.
   ================================================================ */

(function () {
  "use strict";

  const VOICE = {
    status: `${API_BASE}/voice/status`,
    start: `${API_BASE}/voice/start`,
    listen: `${API_BASE}/voice/listen`,
    say: `${API_BASE}/voice/say`,
    photo: `${API_BASE}/voice/photo`,
    speak: `${API_BASE}/voice/speak`,
  };

  const TARGET_RATE = 16000;
  const MAX_RECORD_MS = 12000;      // hard cap so a stuck mic cannot hang
  const SILENCE_HOLD_MS = 1500;     // stop this long after speech ends
  const SILENCE_RMS = 0.012;

  const state = {
    sessionId: null,
    lang: "hi",
    mode: null,          // "server" | "browser"
    serverStatus: null,
    turns: [],           // { role: "agent"|"farmer", text }
    listening: false,
    busy: false,
    finished: false,
    error: null,
    lastData: null,      // model output for the result card
    awaitingPhoto: false,
    options: [],         // tappable answers for the current question
    optionFilter: "",
  };

  let mediaStream = null;
  let audioContext = null;
  let processor = null;
  let sourceNode = null;
  let recordedChunks = [];
  let recordingTimer = null;
  let silenceTimer = null;
  let speechSeen = false;
  let recognition = null;   // browser SpeechRecognition

  // ── Capability probe ───────────────────────────────────────────

  async function probeStatus() {
    try {
      const resp = await fetch(VOICE.status);
      if (!resp.ok) throw new Error(`status ${resp.status}`);
      state.serverStatus = await resp.json();
    } catch (err) {
      state.serverStatus = null;
    }
    state.mode = pickMode();
    return state.mode;
  }

  function pickMode() {
    const s = state.serverStatus;
    const langs = s && s.languages ? s.languages[state.lang] : null;
    if (langs && langs.asr_ready) return "server";
    if (window.SpeechRecognition || window.webkitSpeechRecognition) return "browser";
    return null;
  }

  function serverCanSpeak() {
    const s = state.serverStatus;
    const langs = s && s.languages ? s.languages[state.lang] : null;
    return Boolean(langs && langs.tts_ready);
  }

  // ── WAV encoding ───────────────────────────────────────────────

  function downsample(buffer, fromRate, toRate) {
    if (toRate >= fromRate) return buffer;
    const ratio = fromRate / toRate;
    const out = new Float32Array(Math.round(buffer.length / ratio));
    for (let i = 0; i < out.length; i++) {
      // Average the source window rather than point-sampling, which
      // would alias badly at 48k -> 16k and hurt recognition.
      const start = Math.round(i * ratio);
      const end = Math.min(Math.round((i + 1) * ratio), buffer.length);
      let sum = 0;
      for (let j = start; j < end; j++) sum += buffer[j];
      out[i] = end > start ? sum / (end - start) : 0;
    }
    return out;
  }

  function encodeWav(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    const writeString = (offset, str) => {
      for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
    };

    writeString(0, "RIFF");
    view.setUint32(4, 36 + samples.length * 2, true);
    writeString(8, "WAVE");
    writeString(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);            // PCM
    view.setUint16(22, 1, true);            // mono
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeString(36, "data");
    view.setUint32(40, samples.length * 2, true);

    let offset = 44;
    for (let i = 0; i < samples.length; i++, offset += 2) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return new Blob([view], { type: "audio/wav" });
  }

  // ── Recording ──────────────────────────────────────────────────

  async function startRecording() {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });

    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    sourceNode = audioContext.createMediaStreamSource(mediaStream);
    processor = audioContext.createScriptProcessor(4096, 1, 1);

    recordedChunks = [];
    speechSeen = false;

    processor.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0);
      recordedChunks.push(new Float32Array(input));

      let sum = 0;
      for (let i = 0; i < input.length; i++) sum += input[i] * input[i];
      const rms = Math.sqrt(sum / input.length);

      // Auto-stop once the farmer has spoken and then gone quiet.
      if (rms > SILENCE_RMS) {
        speechSeen = true;
        clearTimeout(silenceTimer);
        silenceTimer = null;
      } else if (speechSeen && !silenceTimer) {
        silenceTimer = setTimeout(() => stopListening(), SILENCE_HOLD_MS);
      }
    };

    sourceNode.connect(processor);
    processor.connect(audioContext.destination);
    recordingTimer = setTimeout(() => stopListening(), MAX_RECORD_MS);
  }

  function teardownRecording() {
    clearTimeout(recordingTimer); recordingTimer = null;
    clearTimeout(silenceTimer); silenceTimer = null;
    if (processor) { processor.onaudioprocess = null; processor.disconnect(); processor = null; }
    if (sourceNode) { sourceNode.disconnect(); sourceNode = null; }
    if (audioContext) { audioContext.close().catch(() => {}); }
    if (mediaStream) { mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; }
  }

  function collectWav() {
    const rate = audioContext ? audioContext.sampleRate : 44100;
    const total = recordedChunks.reduce((n, c) => n + c.length, 0);
    const merged = new Float32Array(total);
    let offset = 0;
    for (const chunk of recordedChunks) { merged.set(chunk, offset); offset += chunk.length; }
    recordedChunks = [];
    return encodeWav(downsample(merged, rate, TARGET_RATE), TARGET_RATE);
  }

  // ── Playback ───────────────────────────────────────────────────

  function speakInBrowser(text) {
    return new Promise((resolve) => {
      if (!window.speechSynthesis) return resolve();
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = state.lang === "hi" ? "hi-IN" : "en-IN";
      utterance.rate = 0.95;
      utterance.onend = resolve;
      utterance.onerror = resolve;
      window.speechSynthesis.speak(utterance);
    });
  }

  async function speak(text) {
    if (!text) return;
    if (serverCanSpeak()) {
      try {
        const body = new FormData();
        body.append("text", text);
        body.append("lang", state.lang);
        const resp = await fetch(VOICE.speak, { method: "POST", body });
        if (resp.ok && resp.status !== 204) {
          const url = URL.createObjectURL(await resp.blob());
          const audio = new Audio(url);
          await new Promise((resolve) => {
            audio.onended = resolve;
            audio.onerror = resolve;
            audio.play().catch(resolve);
          });
          URL.revokeObjectURL(url);
          return;
        }
      } catch (err) {
        // fall through to the browser voice
      }
    }
    await speakInBrowser(text);
  }

  // ── Conversation ───────────────────────────────────────────────

  function pushTurn(role, text) {
    if (!text) return;
    state.turns.push({ role, text });
  }

  async function applyReply(reply) {
    if (reply.transcript) pushTurn("farmer", reply.transcript);
    pushTurn("agent", reply.text);
    if (reply.data) state.lastData = reply.data;
    state.options = reply.options || [];
    state.optionFilter = "";
    state.awaitingPhoto = reply.action === "capture_photo";
    state.finished = reply.action === "end";
    state.busy = false;
    renderPanel();

    await speak(reply.text);

    // Keep the conversation moving without the farmer hunting for the button.
    if (reply.action === "listen" && !state.finished) {
      setTimeout(() => { if (!state.busy && !state.listening) startListening(); }, 250);
    }
  }

  async function postForm(url, fields) {
    const body = new FormData();
    Object.entries(fields).forEach(([k, v]) => body.append(k, v));
    const resp = await fetch(url, { method: "POST", body });
    if (!resp.ok) {
      let detail = `Server error ${resp.status}`;
      try { detail = (await resp.json()).detail || detail; } catch (e) { /* keep default */ }
      throw new Error(detail);
    }
    return resp.json();
  }

  async function beginSession() {
    state.error = null;
    state.busy = true;
    state.turns = [];
    state.lastData = null;
    state.finished = false;
    renderPanel();

    await probeStatus();
    if (!state.mode) {
      state.busy = false;
      state.error = "No speech input available. Download the offline models " +
                    "(python scripts/download_voice_models.py) or use Chrome.";
      renderPanel();
      return;
    }

    try {
      const resp = await fetch(VOICE.start, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lang: state.lang }),
      });
      if (!resp.ok) throw new Error(`Server error ${resp.status}`);
      const reply = await resp.json();
      state.sessionId = reply.session_id;
      await applyReply(reply);
    } catch (err) {
      state.busy = false;
      state.error = `Could not reach the voice server at ${API_BASE}. ` +
                    `Start it with: uvicorn main:app --reload`;
      renderPanel();
    }
  }

  async function startListening() {
    if (state.listening || state.busy || state.finished || !state.sessionId) return;
    state.error = null;
    state.listening = true;
    renderPanel();

    if (state.mode === "browser") return startBrowserRecognition();

    try {
      await startRecording();
    } catch (err) {
      state.listening = false;
      state.error = "Microphone permission is required to talk to the agent.";
      renderPanel();
    }
  }

  async function stopListening() {
    if (!state.listening) return;
    state.listening = false;

    if (state.mode === "browser") {
      if (recognition) recognition.stop();
      renderPanel();
      return;
    }

    const wav = collectWav();
    teardownRecording();
    state.busy = true;
    renderPanel();

    try {
      const body = new FormData();
      body.append("session_id", state.sessionId);
      body.append("audio", wav, "speech.wav");
      const resp = await fetch(VOICE.listen, { method: "POST", body });
      if (!resp.ok) {
        let detail = `Server error ${resp.status}`;
        try { detail = (await resp.json()).detail || detail; } catch (e) { /* default */ }
        throw new Error(detail);
      }
      await applyReply(await resp.json());
    } catch (err) {
      state.busy = false;
      state.error = err.message;
      renderPanel();
    }
  }

  function startBrowserRecognition() {
    const Impl = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new Impl();
    recognition.lang = state.lang === "hi" ? "hi-IN" : "en-IN";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onresult = async (event) => {
      const text = event.results[0][0].transcript;
      state.listening = false;
      state.busy = true;
      renderPanel();
      try {
        await applyReply(await postForm(VOICE.say, {
          session_id: state.sessionId, text,
        }));
      } catch (err) {
        state.busy = false;
        state.error = err.message;
        renderPanel();
      }
    };
    recognition.onerror = (event) => {
      state.listening = false;
      state.error = event.error === "not-allowed"
        ? "Microphone permission is required to talk to the agent."
        : `Could not hear that (${event.error}). Tap the mic to try again.`;
      renderPanel();
    };
    recognition.onend = () => {
      if (state.listening) { state.listening = false; renderPanel(); }
    };
    recognition.start();
  }

  async function sendPhoto(file) {
    if (!file || !state.sessionId) return;
    state.busy = true;
    state.error = null;
    renderPanel();
    try {
      const body = new FormData();
      body.append("session_id", state.sessionId);
      body.append("file", file, file.name || "leaf.jpg");
      const resp = await fetch(VOICE.photo, { method: "POST", body });
      if (!resp.ok) throw new Error(`Server error ${resp.status}`);
      await applyReply(await resp.json());
    } catch (err) {
      state.busy = false;
      state.error = err.message;
      renderPanel();
    }
  }

  async function sendTyped(text) {
    if (!text || !state.sessionId) return;
    state.busy = true;
    renderPanel();
    try {
      await applyReply(await postForm(VOICE.say, {
        session_id: state.sessionId, text,
      }));
    } catch (err) {
      state.busy = false;
      state.error = err.message;
      renderPanel();
    }
  }

  function endSession() {
    if (state.sessionId) {
      fetch(`${API_BASE}/voice/${state.sessionId}`, { method: "DELETE" }).catch(() => {});
    }
    if (state.listening) { teardownRecording(); if (recognition) recognition.stop(); }
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    state.sessionId = null;
    state.listening = false;
    state.busy = false;
    state.finished = false;
    state.turns = [];
    state.awaitingPhoto = false;
    renderPanel();
  }

  // ── Rendering ──────────────────────────────────────────────────

  function modeBadge() {
    if (!state.sessionId) return "";
    if (state.mode === "server") {
      return `<span class="voice-badge voice-badge-offline">${Icons.wifiOff(13)} Offline speech</span>`;
    }
    return `<span class="voice-badge voice-badge-browser">${Icons.globe(13)} Browser speech</span>`;
  }

  function micLabel() {
    if (state.busy) return "Thinking…";
    if (state.listening) return "Listening — tap to stop";
    return "Tap to speak";
  }

  function renderTurns() {
    if (!state.turns.length) return "";
    return state.turns.map(t => `
      <div class="voice-turn voice-turn-${t.role}">
        <span class="voice-turn-who">${t.role === "agent" ? "Crop Sathi" : "You"}</span>
        <p>${escapeHtml(t.text)}</p>
      </div>`).join("");
  }

  /*
     Village and block names are rare proper nouns that the offline model
     cannot reliably hear, so they are offered as a tappable list alongside
     the mic. Districts are recognised well and need no list, but showing one
     costs nothing and keeps the flow moving when recognition does slip.
  */
  function renderOptions() {
    if (!state.options.length || state.finished || state.awaitingPhoto) return "";

    const filter = state.optionFilter.trim().toLowerCase();
    const shown = (filter
      ? state.options.filter(o => o.toLowerCase().includes(filter))
      : state.options).slice(0, 60);

    return `
      <div class="voice-options">
        <div class="voice-options-head">
          <span>Or choose from the list</span>
          ${state.options.length > 12 ? `
            <input type="text" class="voice-options-filter" placeholder="Search…"
                   value="${escapeHtml(state.optionFilter)}"
                   oninput="Voice.filter(this.value)">` : ""}
        </div>
        <div class="voice-options-list">
          ${shown.map(o => `
            <button class="chip" onclick="Voice.pick('${escapeAttr(o)}')">${escapeHtml(o)}</button>
          `).join("")}
          ${shown.length === 0 ? `<span class="voice-hint">No match for that name.</span>` : ""}
        </div>
      </div>`;
  }

  function renderResultCard() {
    const d = state.lastData;
    if (!d) return "";
    if (d.prediction) {
      const pct = Math.round((d.confidence || 0) * 100);
      const alts = (d.top_3 || []).slice(1).join(", ");
      return `
        <div class="voice-result">
          <h4>Recommended crop</h4>
          <p class="voice-result-main">${escapeHtml(d.prediction)} <span>${pct}%</span></p>
          ${alts ? `<p class="voice-result-alt">Alternatives: ${escapeHtml(alts)}</p>` : ""}
          <p class="voice-result-meta">From your village's measured soil —
            N ${d.inputs.N}, P ${d.inputs.P}, K ${d.inputs.K}, pH ${d.inputs.ph},
            rainfall ${d.inputs.rainfall} mm</p>
        </div>`;
    }
    if (d.predicted_class) {
      const pct = Math.round((d.confidence || 0) * 100);
      return `
        <div class="voice-result">
          <h4>Leaf analysis</h4>
          <p class="voice-result-main">${escapeHtml(d.plant_name || "")} — ${escapeHtml(d.disease_status || "")} <span>${pct}%</span></p>
          ${pct < 75 ? `<p class="voice-result-alt">Below the reliability threshold — the agent
            deliberately did not state a diagnosis.</p>` : ""}
        </div>`;
    }
    return "";
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  // Place names legitimately contain apostrophes, which would otherwise
  // terminate the inline onclick string early.
  function escapeAttr(s) {
    return String(s).replace(/\\/g, "\\\\").replace(/'/g, "\\'")
                    .replace(/"/g, "&quot;").replace(/</g, "&lt;");
  }

  function renderPanel() {
    const panel = document.querySelector("#voice-panel");
    if (panel) panel.innerHTML = panelHtml();
  }

  function panelHtml() {
    if (!state.sessionId) {
      return `
        <div class="voice-idle">
          <button class="btn btn-primary btn-lg" onclick="Voice.begin()">
            ${Icons.mic(20)} Start talking
          </button>
          <p class="voice-hint">The agent will ask your name, your village, and what you need.
            It answers using your village's real soil test — nothing is made up.</p>
          ${state.error ? `<div class="voice-error">${escapeHtml(state.error)}</div>` : ""}
        </div>`;
    }

    return `
      <div class="voice-live">
        <div class="voice-head">
          ${modeBadge()}
          <button class="btn-ghost" onclick="Voice.end()">End</button>
        </div>

        <div class="voice-transcript" id="voice-transcript">${renderTurns()}</div>
        ${renderOptions()}
        ${renderResultCard()}
        ${state.error ? `<div class="voice-error">${escapeHtml(state.error)}</div>` : ""}

        <div class="voice-controls">
          ${state.finished ? `
            <button class="btn btn-primary" onclick="Voice.begin()">Start again</button>
          ` : state.awaitingPhoto ? `
            <label class="btn btn-primary voice-photo-btn">
              ${Icons.camera ? Icons.camera(18) : ""} Take leaf photo
              <input type="file" accept="image/*" capture="environment"
                     onchange="Voice.photo(this.files[0])" hidden>
            </label>
          ` : `
            <button class="voice-mic ${state.listening ? "is-listening" : ""}"
                    onclick="Voice.mic()" ${state.busy ? "disabled" : ""}>
              ${Icons.mic(28)}
            </button>
            <span class="voice-mic-label">${micLabel()}</span>
          `}
        </div>

        <details class="voice-fallback">
          <summary>Type instead</summary>
          <form onsubmit="Voice.typed(event)">
            <input type="text" id="voice-typed" placeholder="Type your answer…" autocomplete="off">
            <button class="btn btn-secondary" type="submit">Send</button>
          </form>
        </details>
      </div>`;
  }

  function renderPage() {
    return `
      <section class="section">
        <div class="container">
          <div class="section-header">
            <h2 class="section-title">Voice assistant</h2>
            <p class="section-subtitle">Talk to Crop Sathi in Hindi or English. Works without internet.</p>
          </div>

          <div class="voice-lang-switch">
            <button class="chip ${state.lang === "hi" ? "chip-active" : ""}"
                    onclick="Voice.setLang('hi')">हिंदी</button>
            <button class="chip ${state.lang === "en" ? "chip-active" : ""}"
                    onclick="Voice.setLang('en')">English</button>
          </div>

          <div class="voice-panel card" id="voice-panel">${panelHtml()}</div>
        </div>
      </section>`;
  }

  // ── Public API ─────────────────────────────────────────────────

  window.Voice = {
    renderPage,
    init() { probeStatus().then(renderPanel); },

    begin() { beginSession(); },
    end() { endSession(); },
    mic() { state.listening ? stopListening() : startListening(); },
    photo(file) { sendPhoto(file); },

    pick(value) {
      // Stop the mic first: the agent auto-listens after each turn, and a
      // live recogniser would otherwise send a stray utterance behind the tap.
      if (state.listening) {
        state.listening = false;
        if (state.mode === "browser" && recognition) recognition.stop();
        else teardownRecording();
      }
      state.options = [];
      sendTyped(value);
    },

    filter(value) {
      state.optionFilter = value;
      const list = document.querySelector(".voice-options-list");
      if (!list) return;
      // Re-render just the list so the search box keeps focus and caret.
      const panel = document.querySelector("#voice-panel .voice-options");
      if (panel) {
        const fresh = document.createElement("div");
        fresh.innerHTML = renderOptions();
        const newList = fresh.querySelector(".voice-options-list");
        if (newList) list.innerHTML = newList.innerHTML;
      }
    },

    setLang(lang) {
      if (state.lang === lang) return;
      state.lang = lang;
      // A conversation is tied to its language on the server, so switching
      // starts a fresh one rather than continuing mid-dialogue in a new tongue.
      if (state.sessionId) endSession();
      state.mode = pickMode();
      // app.js re-renders the whole page on hashchange, which redraws the
      // language chips as well as the panel.
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    },

    typed(event) {
      event.preventDefault();
      const input = document.querySelector("#voice-typed");
      if (!input) return;
      const text = input.value.trim();
      input.value = "";
      if (text) sendTyped(text);
    },
  };
})();
