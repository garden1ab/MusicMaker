(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const api = (p, opts) => fetch(p, opts).then((r) => {
    if (!r.ok) return r.json().then((j) => { throw new Error(j.detail || r.statusText); });
    return r.json();
  });

  const state = {
    mode: "genre",
    catalog: null,
    instruments: new Set(),
    structure: [],
    vocalStyles: new Set(),
    refAudioId: null,
    refRole: "music",
    polling: null,
  };

  // ---------- status badge + logo waveform ----------
  function animateLogo() {
    const poly = $("logoWave");
    let t = 0;
    setInterval(() => {
      t += 0.18;
      const pts = [];
      for (let x = 0; x <= 64; x += 2) {
        const y = 16 + Math.sin(x * 0.25 + t) * 7 * Math.sin(t * 0.5 + x * 0.05);
        pts.push(`${x},${y.toFixed(1)}`);
      }
      poly.setAttribute("points", pts.join(" "));
    }, 60);
  }

  async function loadStatus() {
    const badge = $("statusBadge");
    try {
      const s = await api("/api/status_info");
      if (s.mode === "gpu") {
        badge.className = "status-badge gpu";
        $("statusText").textContent = `${s.gpu} · ${s.vram_gb ?? "?"}GB`;
      } else if (s.mode === "demo") {
        badge.className = "status-badge demo";
        $("statusText").textContent = "demo mode (no GPU)";
      } else if (s.mode === "cpu") {
        badge.className = "status-badge demo";
        $("statusText").textContent = "cpu only — slow";
      } else {
        badge.className = "status-badge bad";
        $("statusText").textContent = s.error ? "model error" : s.mode;
      }
    } catch (e) {
      badge.className = "status-badge bad";
      $("statusText").textContent = "offline";
    }
  }

  // ---------- catalog ----------
  async function loadCatalog() {
    const c = await api("/api/catalog");
    state.catalog = c;

    // genres
    const genreSel = $("genre");
    const blendSel = $("blendGenre");
    Object.keys(c.genres).forEach((g) => {
      genreSel.add(new Option(g, g));
      blendSel.add(new Option(g, g));
    });
    genreSel.value = Object.keys(c.genres)[0];
    populateSubgenres();
    genreSel.addEventListener("change", populateSubgenres);

    // keys
    c.keys.forEach((k) => $("key").add(new Option(k, k)));

    // instruments
    const ic = $("instruments");
    c.instruments.forEach((inst) => {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = inst;
      chip.addEventListener("click", () => {
        if (state.instruments.has(inst)) { state.instruments.delete(inst); chip.classList.remove("on"); }
        else { state.instruments.add(inst); chip.classList.add("on"); }
        $("instReadout").textContent = state.instruments.size ? `${state.instruments.size} selected` : "any";
      });
      ic.appendChild(chip);
    });

    // structure blocks
    const sc = $("structure");
    c.structure_blocks.forEach((b) => {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = b;
      chip.dataset.block = b;
      chip.addEventListener("click", () => toggleStructure(b, chip));
      sc.appendChild(chip);
    });

    // tempo feels (quick presets)
    const tf = $("tempoFeels");
    const feelBpm = { "very slow": 55, slow: 72, relaxed: 88, moderate: 104, upbeat: 120, fast: 136, "very fast": 152, frenetic: 174 };
    (c.tempo_feels || Object.keys(feelBpm)).forEach((name) => {
      const span = document.createElement("span");
      span.textContent = name;
      span.addEventListener("click", () => { $("tempo").value = feelBpm[name] || 110; updateTempo(); });
      tf.appendChild(span);
    });

    // duration cap
    if (c.max_duration) $("duration").max = c.max_duration;

    // vocals
    const v = c.vocals || { genders: [], styles: [], languages: [] };
    v.genders.forEach((g) => $("vocalGender").add(new Option(g, g)));
    v.languages.forEach((l) => $("language").add(new Option(l, l)));
    $("language").value = "English";
    const vsc = $("vocalStyles");
    v.styles.forEach((s) => {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = s;
      chip.addEventListener("click", () => {
        if (state.vocalStyles.has(s)) { state.vocalStyles.delete(s); chip.classList.remove("on"); }
        else { state.vocalStyles.add(s); chip.classList.add("on"); }
        $("vstyleReadout").textContent = state.vocalStyles.size ? `${state.vocalStyles.size} selected` : "default";
      });
      vsc.appendChild(chip);
    });
  }

  function populateSubgenres() {
    const g = $("genre").value;
    const sub = $("subgenre");
    sub.innerHTML = "";
    sub.add(new Option("— any —", ""));
    (state.catalog.genres[g] || []).forEach((s) => sub.add(new Option(s, s)));
  }

  function toggleStructure(block, chip) {
    const idx = state.structure.indexOf(block);
    if (idx >= 0) { state.structure.splice(idx, 1); chip.classList.remove("on"); }
    else { state.structure.push(block); chip.classList.add("on"); }
    renderSequence();
  }

  function renderSequence() {
    const seq = $("structSeq");
    seq.innerHTML = "";
    state.structure.forEach((b, i) => {
      const pill = document.createElement("span");
      pill.className = "seq-pill";
      pill.innerHTML = `<span class="n">${i + 1}</span>${b}`;
      seq.appendChild(pill);
    });
    $("structReadout").textContent = state.structure.length ? `${state.structure.length} blocks` : "model decides";
  }

  // ---------- vocals + reference role ----------
  function setupVocals() {
    $("vocalsOn").addEventListener("change", (e) => {
      $("vocalPanel").hidden = !e.target.checked;
    });
    $("insertStructure").addEventListener("click", () => {
      const blocks = state.structure.length ? state.structure : ["verse", "chorus", "verse", "chorus", "bridge", "chorus"];
      const ta = $("lyrics");
      const scaffold = blocks.map((b) => `[${b}]\n`).join("\n");
      ta.value = ta.value.trim() ? ta.value.trim() + "\n\n" + scaffold : scaffold;
      ta.focus();
    });
    $("lyricAdherence").addEventListener("input", (e) => {
      const v = +e.target.value;
      const label = v === 0 ? "model default" : v <= 3 ? `subtle (${v})` : v <= 6 ? `balanced (${v})` : `strict (${v})`;
      $("lyricAdhReadout").textContent = label;
    });
  }

  function setupRefRole() {
    $("refRoleSwitch").querySelectorAll(".mini-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        $("refRoleSwitch").querySelectorAll(".mini-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        state.refRole = btn.dataset.role;
        const voice = state.refRole === "voice";
        $("refRoleHint").textContent = voice
          ? "Carry the reference singer's timbre into the generated vocals (zero-shot voice match). Best with vocals on."
          : "Generate a new track guided by the clip's musical style (audio2audio).";
        $("refStrengthLabel").childNodes[0].nodeValue = voice ? "Match voice strength " : "Stay close to reference ";
        $("consentWrap").hidden = !(voice && state.refAudioId);
        // Voice matching wants a higher default strength.
        if (voice && $("refStrength").value === "50") { $("refStrength").value = 75; $("refReadout").textContent = "0.75"; }
      });
    });
  }

  // ---------- mode switch ----------
  function setupModes() {
    document.querySelectorAll(".mode-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".mode-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        state.mode = btn.dataset.mode;
        $("paneText").hidden = state.mode !== "text";
        $("paneGenre").hidden = state.mode !== "genre";
      });
    });
  }

  // ---------- sliders readouts ----------
  function setupSliders() {
    $("energy").addEventListener("input", (e) => $("energyReadout").textContent = e.target.value);
    $("tempo").addEventListener("input", updateTempo);
    $("duration").addEventListener("input", (e) => $("durReadout").textContent = `${e.target.value}s`);
    $("steps").addEventListener("input", (e) => $("stepsReadout").textContent = e.target.value);
    $("guidance").addEventListener("input", (e) => $("guidanceReadout").textContent = e.target.value);
    $("refStrength").addEventListener("input", (e) => $("refReadout").textContent = (e.target.value / 100).toFixed(2));
    $("blendAmount").addEventListener("input", updateBlend);
  }
  function updateTempo() { $("tempoReadout").textContent = `${$("tempo").value} bpm`; }
  function updateBlend() {
    const v = +$("blendAmount").value;
    const g = $("blendGenre").value;
    $("blendReadout").textContent = (!g || v === 0) ? "off" : `${g} · ${v}%`;
  }
  $("blendGenre") && document.addEventListener("change", (e) => { if (e.target.id === "blendGenre") updateBlend(); });

  // ---------- upload ----------
  function setupUpload() {
    const dz = $("dropzone"), fi = $("fileInput");
    $("browseBtn").addEventListener("click", (e) => { e.stopPropagation(); fi.click(); });
    dz.addEventListener("click", () => fi.click());
    dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("drag"); });
    dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
    dz.addEventListener("drop", (e) => {
      e.preventDefault(); dz.classList.remove("drag");
      if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
    });
    fi.addEventListener("change", () => { if (fi.files[0]) handleFile(fi.files[0]); });
  }

  async function handleFile(file) {
    const dz = $("dropzone");
    $("dzInner").innerHTML = `<span class="dz-icon">⟳</span><p>uploading ${file.name}…</p>`;
    try {
      const fd = new FormData(); fd.append("file", file);
      const res = await api("/api/upload", { method: "POST", body: fd });
      state.refAudioId = res.ref_audio_id;
      dz.classList.add("loaded");
      $("dzInner").innerHTML = `<span class="dz-icon">✓</span><p>${res.filename}</p>
        <p class="hint"><button type="button" class="link" id="clearRef">remove</button></p>`;
      $("refStrengthWrap").hidden = false;
      if (state.refRole === "voice") $("consentWrap").hidden = false;
      $("clearRef").addEventListener("click", (e) => { e.stopPropagation(); clearRef(); });
    } catch (err) {
      $("dzInner").innerHTML = `<span class="dz-icon">⚠</span><p>upload failed</p><p class="hint">${err.message}</p>`;
    }
  }
  function clearRef() {
    state.refAudioId = null;
    $("dropzone").classList.remove("loaded");
    $("refStrengthWrap").hidden = true;
    $("consentWrap").hidden = true;
    if ($("cloneConsent")) $("cloneConsent").checked = false;
    $("dzInner").innerHTML = `<span class="dz-icon">⤓</span>
      <p>Drop an audio clip or <button type="button" class="link" id="browseBtn">browse</button></p>
      <p class="hint">wav / mp3 / flac · up to 50&nbsp;MB</p>`;
    $("browseBtn").addEventListener("click", (e) => { e.stopPropagation(); $("fileInput").click(); });
  }

  // ---------- visualizer (oscilloscope) ----------
  const scope = $("scope");
  const sctx = scope.getContext("2d");
  let audioCtx, analyser, vizMode = "idle", rafId;
  function sizeCanvas() {
    const r = scope.getBoundingClientRect();
    scope.width = r.width * devicePixelRatio; scope.height = r.height * devicePixelRatio;
    sctx.scale(devicePixelRatio, devicePixelRatio);
  }
  function drawScope() {
    const r = scope.getBoundingClientRect();
    sctx.clearRect(0, 0, r.width, r.height);
    // grid
    sctx.strokeStyle = "rgba(67,215,208,0.06)"; sctx.lineWidth = 1;
    for (let x = 0; x < r.width; x += 28) { sctx.beginPath(); sctx.moveTo(x, 0); sctx.lineTo(x, r.height); sctx.stroke(); }
    for (let y = 0; y < r.height; y += 28) { sctx.beginPath(); sctx.moveTo(0, y); sctx.lineTo(r.width, y); sctx.stroke(); }

    let data;
    if (vizMode === "live" && analyser) {
      data = new Uint8Array(analyser.fftSize); analyser.getByteTimeDomainData(data);
    }
    sctx.beginPath();
    const grad = sctx.createLinearGradient(0, 0, r.width, 0);
    grad.addColorStop(0, "#43d7d0"); grad.addColorStop(1, "#ff9d3c");
    sctx.strokeStyle = grad; sctx.lineWidth = 2;
    sctx.shadowColor = "rgba(67,215,208,0.6)"; sctx.shadowBlur = 8;
    const N = data ? data.length : 256;
    for (let i = 0; i < N; i++) {
      const x = (i / (N - 1)) * r.width;
      let v;
      if (data) v = (data[i] / 128 - 1);
      else {
        const t = performance.now() / 1000;
        const amp = vizMode === "working" ? 0.5 : 0.12;
        v = Math.sin(i * 0.08 + t * 3) * amp * Math.sin(i * 0.02 + t);
      }
      const y = r.height / 2 + v * (r.height / 2 - 6);
      i === 0 ? sctx.moveTo(x, y) : sctx.lineTo(x, y);
    }
    sctx.stroke(); sctx.shadowBlur = 0;
    rafId = requestAnimationFrame(drawScope);
  }
  function setViz(mode, status, sub) {
    vizMode = mode;
    if (status !== undefined) $("vizStatus").textContent = status;
    if (sub !== undefined) $("vizSub").textContent = sub;
    $("vizOverlay").style.opacity = mode === "live" ? 0 : 1;
  }
  function attachAnalyser(audioEl) {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const src = audioCtx.createMediaElementSource(audioEl);
    analyser = audioCtx.createAnalyser(); analyser.fftSize = 1024;
    src.connect(analyser); analyser.connect(audioCtx.destination);
  }

  // ---------- generate ----------
  function collectRequest() {
    const tempo = $("tempo").value;
    const seedVal = $("seed").value.trim();
    const vocalsOn = $("vocalsOn").checked;
    const adh = +$("lyricAdherence").value;
    return {
      mode: state.mode,
      text_prompt: $("textPrompt").value,
      genre: $("genre").value,
      subgenre: $("subgenre").value || null,
      blend_genre: $("blendGenre").value || null,
      blend_amount: +$("blendAmount").value,
      instruments: [...state.instruments],
      energy: +$("energy").value,
      tempo: tempo,
      key: $("key").value || null,
      structure: state.structure,
      instrumental: !vocalsOn,
      extra_tags: $("extraTags").value || null,
      // vocals
      lyrics: vocalsOn ? ($("lyrics").value || null) : null,
      vocal_gender: vocalsOn ? ($("vocalGender").value || null) : null,
      vocal_styles: vocalsOn ? [...state.vocalStyles] : [],
      language: vocalsOn ? ($("language").value || null) : null,
      lyric_adherence: (vocalsOn && adh > 0) ? adh : null,
      // output
      duration: +$("duration").value,
      seed: seedVal === "" ? null : +seedVal,
      infer_steps: +$("steps").value,
      guidance_scale: +$("guidance").value,
      // reference
      ref_audio_id: state.refAudioId,
      ref_audio_strength: +$("refStrength").value / 100,
      ref_role: state.refRole,
      clone_consent: $("cloneConsent") ? $("cloneConsent").checked : false,
    };
  }

  async function generate() {
    const btn = $("generateBtn");
    $("errBox").hidden = true;
    $("resultMeta").hidden = true;
    $("player").hidden = true;
    btn.disabled = true;
    btn.querySelector(".gen-label").textContent = "Generating";
    btn.querySelector(".gen-spinner").hidden = false;
    $("progressWrap").hidden = false;
    setProgress(0.03, "Submitting…");
    setViz("working", "Generating", "Sampling latent audio…");

    try {
      const req = collectRequest();
      if (req.ref_audio_id && req.ref_role === "voice" && !req.clone_consent) {
        resetBtn(); $("progressWrap").hidden = true;
        $("errBox").textContent = "Please confirm you have the right to use the uploaded voice.";
        $("errBox").hidden = false;
        setViz("idle", "Hold on", "Confirm voice rights to continue.");
        return;
      }
      const { job_id } = await api("/api/generate", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
      });
      pollJob(job_id);
    } catch (err) { fail(err.message); }
  }

  function pollJob(jobId) {
    clearInterval(state.polling);
    state.polling = setInterval(async () => {
      try {
        const s = await api(`/api/jobs/${jobId}`);
        setProgress(s.progress || 0, s.message || "");
        if (s.status === "done") { clearInterval(state.polling); finish(s); }
        else if (s.status === "error") { clearInterval(state.polling); fail(s.error || "generation failed"); }
      } catch (err) { clearInterval(state.polling); fail(err.message); }
    }, 800);
  }

  function setProgress(p, msg) {
    $("progressFill").style.width = `${Math.round(p * 100)}%`;
    $("progressMsg").textContent = msg;
  }

  function finish(s) {
    resetBtn();
    $("progressWrap").hidden = true;
    const player = $("player");
    player.src = s.audio_url + "?t=" + Date.now();
    player.hidden = false;
    try { if (!analyser) attachAnalyser(player); } catch (e) { /* analyser attaches once */ }
    player.onplay = () => { if (audioCtx && audioCtx.state === "suspended") audioCtx.resume(); setViz("live"); };
    player.onpause = () => setViz("idle", "Ready", "Press play to view the waveform.");
    setViz("idle", "Done ✓", "Press play.");
    $("metaPrompt").textContent = s.prompt_used || "";
    $("metaSeed").textContent = s.seed ?? "—";
    const reuse = $("reuseSeed");
    if (s.seed != null) {
      reuse.hidden = false;
      reuse.onclick = () => {
        $("seed").value = s.seed;
        const adv = document.querySelector(".advanced");
        if (adv && !adv.open) adv.open = true;          // reveal the seed field
        $("seed").focus();
        reuse.classList.add("flash");
        setTimeout(() => reuse.classList.remove("flash"), 500);
      };
    } else {
      reuse.hidden = true;
    }
    $("downloadBtn").href = s.audio_url;
    $("resultMeta").hidden = false;
  }

  function fail(msg) {
    resetBtn();
    clearInterval(state.polling);
    $("progressWrap").hidden = true;
    $("errBox").textContent = msg;
    $("errBox").hidden = false;
    setViz("idle", "Error", "Check settings and try again.");
  }
  function resetBtn() {
    const btn = $("generateBtn");
    btn.disabled = false;
    btn.querySelector(".gen-label").textContent = "Generate";
    btn.querySelector(".gen-spinner").hidden = true;
  }

  // ---------- init ----------
  window.addEventListener("resize", sizeCanvas);
  document.addEventListener("DOMContentLoaded", async () => {
    sizeCanvas(); drawScope(); animateLogo();
    setupModes(); setupSliders(); setupUpload(); setupVocals(); setupRefRole();
    $("generateBtn").addEventListener("click", generate);
    setViz("idle", "Ready", "Configure your track and hit generate.");
    await loadStatus();
    try { await loadCatalog(); } catch (e) { fail("Failed to load catalog: " + e.message); }
    updateTempo();
  });
})();
