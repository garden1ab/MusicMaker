"""
main.py
=======
FastAPI application exposing the music studio.

Routes
------
GET  /                     -> the web UI (static/index.html)
GET  /api/catalog          -> genres, subgenres, instruments, keys, etc.
GET  /api/status_info      -> GPU/model/demo status for the header
POST /api/upload           -> upload a reference clip (for audio2audio)
POST /api/generate         -> queue a generation job, returns job_id
GET  /api/jobs/{job_id}    -> poll job status
GET  /api/audio/{job_id}   -> download/stream the produced audio

A single-worker background thread pool processes jobs sequentially, which is
the right model for one GPU: generations don't fight over VRAM.
"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, prompt_composer, pipeline
from .schemas import GenerateRequest, GenerateResponse, JobStatus, UploadResponse

app = FastAPI(title="AI Music Studio", version="1.0.0")

# In-memory job registry. For a single-node tool this is sufficient; swap for
# Redis if you ever scale horizontally.
_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()

# One worker => one generation at a time => no VRAM contention.
_EXECUTOR = ThreadPoolExecutor(max_workers=1)

KEYS = [
    f"{n} {m}"
    for m in ("major", "minor")
    for n in ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
]

COMMON_INSTRUMENTS = [
    "piano", "acoustic guitar", "electric guitar", "bass guitar", "synth bass",
    "analog synth", "drum machine", "live drums", "strings", "violin", "cello",
    "saxophone", "trumpet", "brass section", "flute", "organ", "rhodes",
    "808 bass", "pads", "arpeggiator", "vocals", "choir", "percussion",
    "banjo", "harp", "marimba", "sitar",
]

STRUCTURE_BLOCKS = [
    "intro", "verse", "pre-chorus", "chorus", "bridge",
    "drop", "breakdown", "build", "solo", "outro",
]

TEMPO_FEELS = list(prompt_composer.TEMPO_NAMES.keys())


def _set_job(job_id: str, **fields) -> None:
    with _JOBS_LOCK:
        _JOBS.setdefault(job_id, {})
        _JOBS[job_id].update(fields)


def _get_job(job_id: str) -> Optional[dict]:
    with _JOBS_LOCK:
        return dict(_JOBS[job_id]) if job_id in _JOBS else None


# ---------------------------------------------------------------------------
# Metadata endpoints
# ---------------------------------------------------------------------------
@app.get("/api/catalog")
def catalog():
    return {
        "genres": prompt_composer.catalog(),
        "instruments": COMMON_INSTRUMENTS,
        "keys": KEYS,
        "structure_blocks": STRUCTURE_BLOCKS,
        "tempo_feels": TEMPO_FEELS,
        "max_duration": config.MAX_DURATION,
    }


@app.get("/api/status_info")
def status_info():
    return pipeline.gpu_info()


# ---------------------------------------------------------------------------
# Upload reference clip for audio2audio
# ---------------------------------------------------------------------------
@app.post("/api/upload", response_model=UploadResponse)
async def upload(file: UploadFile = File(...)):
    ref_id = uuid.uuid4().hex[:12]
    suffix = Path(file.filename or "clip.wav").suffix or ".wav"
    dest = config.UPLOAD_DIR / f"{ref_id}{suffix}"
    data = await file.read()
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB).")
    dest.write_bytes(data)
    return UploadResponse(ref_audio_id=ref_id, filename=file.filename or dest.name)


def _resolve_ref(ref_id: Optional[str]) -> Optional[Path]:
    if not ref_id:
        return None
    matches = list(config.UPLOAD_DIR.glob(f"{ref_id}.*"))
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
def _run_job(job_id: str, req: GenerateRequest, composed: dict) -> None:
    def progress(p: float, msg: str = ""):
        _set_job(job_id, status="running", progress=round(p, 3), message=msg)

    try:
        _set_job(job_id, status="running", progress=0.05, message="Preparing...")
        out_path = config.OUTPUT_DIR / f"{job_id}.wav"
        ref_path = _resolve_ref(req.ref_audio_id)
        duration = max(4.0, min(req.duration, config.MAX_DURATION))

        used_seed = pipeline.run_generation(
            prompt=composed["prompt"],
            lyrics=composed["lyrics"],
            duration=duration,
            infer_steps=req.infer_steps,
            guidance_scale=req.guidance_scale,
            seed=req.seed,
            out_path=out_path,
            ref_audio_path=ref_path,
            ref_audio_strength=req.ref_audio_strength,
            variant=req.model_variant,
            progress_cb=progress,
        )

        if not out_path.exists():
            raise RuntimeError("Generation finished but no audio file was written.")

        _set_job(
            job_id,
            status="done",
            progress=1.0,
            message="Complete",
            audio_url=f"/api/audio/{job_id}",
            seed=used_seed,
            duration=duration,
        )
    except Exception as e:  # noqa: BLE001
        _set_job(job_id, status="error", message="Generation failed", error=str(e))


@app.post("/api/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    composed = prompt_composer.compose(
        mode=req.mode,
        text_prompt=req.text_prompt,
        genre=req.genre,
        subgenre=req.subgenre,
        blend_genre=req.blend_genre,
        blend_amount=req.blend_amount,
        instruments=req.instruments,
        energy=req.energy,
        tempo=req.tempo,
        key=req.key,
        structure=req.structure,
        instrumental=req.instrumental,
        extra_tags=req.extra_tags,
    )
    if not composed["prompt"].strip():
        raise HTTPException(status_code=400, detail="Empty prompt - pick a genre or enter a description.")

    job_id = uuid.uuid4().hex[:12]
    _set_job(
        job_id,
        status="queued",
        progress=0.0,
        message="Queued",
        prompt_used=composed["prompt"],
        lyrics_used=composed["lyrics"],
        created=time.time(),
    )
    _EXECUTOR.submit(_run_job, job_id, req, composed)
    return GenerateResponse(job_id=job_id, status="queued")


@app.get("/api/jobs/{job_id}", response_model=JobStatus)
def job_status(job_id: str):
    job = _get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id.")
    return JobStatus(
        job_id=job_id,
        status=job.get("status", "unknown"),
        progress=job.get("progress", 0.0),
        message=job.get("message", ""),
        audio_url=job.get("audio_url"),
        prompt_used=job.get("prompt_used"),
        lyrics_used=job.get("lyrics_used"),
        duration=job.get("duration"),
        seed=job.get("seed"),
        error=job.get("error"),
    )


@app.get("/api/audio/{job_id}")
def get_audio(job_id: str):
    path = config.OUTPUT_DIR / f"{job_id}.wav"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio not ready.")
    return FileResponse(path, media_type="audio/wav", filename=f"{job_id}.wav")


# ---------------------------------------------------------------------------
# Static front-end (mounted last so /api/* takes precedence)
# ---------------------------------------------------------------------------
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if _STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")


@app.exception_handler(404)
async def spa_fallback(request, exc):  # noqa: ANN001
    # Let API 404s pass through as JSON; everything else falls back to index.
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    index = _STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(status_code=404, content={"detail": "Not found"})
