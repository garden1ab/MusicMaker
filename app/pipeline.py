"""
pipeline.py
===========
Thin, defensive wrapper around the ACE-Step pipeline.

Design goals:
* Lazy import: torch / acestep are only imported when a real generation is
  requested, so the FastAPI app (and the unit tests) start instantly and run
  on machines without a GPU.
* Version-defensive: ACE-Step's constructor and __call__ signatures have
  shifted between v1 and v1.5. We introspect the real signature and pass only
  the kwargs it accepts, so the wrapper survives minor upstream changes.
* Demo mode: when DEMO_MODE=1 (or torch is unavailable) we synthesise a short
  placeholder tone instead of loading the model, which lets you click through
  the entire UI with no GPU.
"""
from __future__ import annotations

import inspect
import math
import random
import struct
import threading
import wave
from pathlib import Path
from typing import Optional

from . import config


class _PipelineHolder:
    """Holds the lazily-constructed ACE-Step pipeline (single instance)."""

    def __init__(self) -> None:
        self._pipe = None
        self._lock = threading.Lock()
        self._loaded_variant: Optional[str] = None

    # -- loading ------------------------------------------------------------
    def _import_pipeline_cls(self):
        # ACE-Step moved the class around between releases; try known paths.
        errors = []
        for path in (
            "acestep.pipeline_ace_step",
            "acestep.pipeline",
            "acestep.acestep_pipeline",
        ):
            try:
                module = __import__(path, fromlist=["ACEStepPipeline"])
                return getattr(module, "ACEStepPipeline")
            except Exception as e:  # noqa: BLE001
                errors.append(f"{path}: {e}")
        raise ImportError(
            "Could not import ACEStepPipeline from any known location.\n"
            + "\n".join(errors)
        )

    def _filtered_kwargs(self, callable_obj, candidate: dict) -> dict:
        """Keep only the kwargs that `callable_obj` actually accepts."""
        try:
            sig = inspect.signature(callable_obj)
        except (TypeError, ValueError):
            return candidate
        # If the callable takes **kwargs, pass everything.
        if any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
            return candidate
        allowed = set(sig.parameters.keys())
        return {k: v for k, v in candidate.items() if k in allowed}

    def load(self, variant: str) -> None:
        with self._lock:
            if self._pipe is not None and self._loaded_variant == variant:
                return
            cls = self._import_pipeline_cls()
            ctor_kwargs = {
                "checkpoint_dir": str(config.CHECKPOINT_DIR),
                "dtype": config.DTYPE,
                "torch_compile": config.TORCH_COMPILE,
                "cpu_offload": config.CPU_OFFLOAD,
                "overlapped_decode": config.OVERLAPPED_DECODE,
                "device_id": config.DEVICE_ID,
            }
            ctor_kwargs = self._filtered_kwargs(cls.__init__, ctor_kwargs)
            self._pipe = cls(**ctor_kwargs)
            self._loaded_variant = variant

    # -- generation ---------------------------------------------------------
    def generate(
        self,
        *,
        prompt: str,
        lyrics: str,
        duration: float,
        infer_steps: int,
        guidance_scale: float,
        seed: Optional[int],
        out_path: Path,
        ref_audio_path: Optional[Path],
        ref_audio_strength: float,
        variant: str,
        lyric_adherence: Optional[float] = None,
        vocal_lora: Optional[str] = None,
        progress_cb=None,
    ) -> int:
        """Run a real generation. Returns the seed actually used."""
        self.load(variant)
        if progress_cb:
            progress_cb(0.15, "Model loaded, sampling...")

        manual_seeds = [seed]

        call_kwargs = {
            "audio_duration": float(duration),
            "prompt": prompt,
            "lyrics": lyrics or "",
            "infer_step": int(infer_steps),
            "guidance_scale": float(guidance_scale),
            "scheduler_type": "euler",
            "cfg_type": "apg",
            "omega_scale": 10.0,
            "manual_seeds": manual_seeds,
            "guidance_interval": 0.5,
            "guidance_interval_decay": 0.0,
            "min_guidance_scale": 3.0,
            "use_erg_tag": True,
            "use_erg_lyric": True,
            "use_erg_diffusion": True,
            "guidance_scale_text": 0.0,
            "guidance_scale_lyric": 0.0,
            "save_path": str(out_path),
            "format": "wav",
            "batch_size": 1,
        }

        # Stronger lyric guidance makes the model adhere more tightly to the
        # provided words / melody-around-words.
        if lyric_adherence is not None:
            call_kwargs["guidance_scale_lyric"] = float(lyric_adherence)

        # Optional Lyric2Vocal (or other) LoRA for pure-vocal generation.
        if vocal_lora:
            call_kwargs["lora_name_or_path"] = vocal_lora

        # Audio2Audio: build from an uploaded reference clip OR carry a
        # reference singer's timbre (zero-shot voice matching). Both use the
        # same conditioning path in the open ACE-Step pipeline.
        if ref_audio_path is not None:
            call_kwargs.update(
                {
                    "audio2audio_enable": True,
                    "ref_audio_input": str(ref_audio_path),
                    "ref_audio_strength": float(ref_audio_strength),
                }
            )

        call_kwargs = self._filtered_kwargs(self._pipe.__call__, call_kwargs)
        if progress_cb:
            progress_cb(0.25, "Generating audio...")
        self._pipe(**call_kwargs)
        if progress_cb:
            progress_cb(0.95, "Finalising...")

        # ACE-Step writes to save_path; some versions append an index. Normalise.
        if not out_path.exists():
            cand = sorted(out_path.parent.glob(out_path.stem + "*"))
            if cand:
                cand[0].rename(out_path)
        return seed


_holder = _PipelineHolder()


# ---------------------------------------------------------------------------
# Public entry point used by the API layer
# ---------------------------------------------------------------------------
def run_generation(
    *,
    prompt: str,
    lyrics: str,
    duration: float,
    infer_steps: int,
    guidance_scale: float,
    seed: Optional[int],
    out_path: Path,
    ref_audio_path: Optional[Path] = None,
    ref_audio_strength: float = 0.5,
    variant: Optional[str] = None,
    lyric_adherence: Optional[float] = None,
    vocal_lora: Optional[str] = None,
    progress_cb=None,
) -> int:
    variant = variant or config.DEFAULT_MODEL

    # Always resolve to a concrete seed so the UI can show it and the user can
    # reproduce or tweak the result. "Random" just means we pick the number.
    if seed is None:
        seed = random.randint(0, 2**32 - 1)

    # Demo / no-GPU fallback ------------------------------------------------
    if config.DEMO_MODE or not _torch_available():
        if progress_cb:
            progress_cb(0.5, "DEMO mode: synthesising placeholder tone")
        _write_demo_tone(out_path, duration=min(duration, 12), seed=seed)
        if progress_cb:
            progress_cb(1.0, "Done (demo)")
        return seed

    # Real generation -------------------------------------------------------
    return _holder.generate(
        prompt=prompt,
        lyrics=lyrics,
        duration=duration,
        infer_steps=infer_steps,
        guidance_scale=guidance_scale,
        seed=seed,
        out_path=out_path,
        ref_audio_path=ref_audio_path,
        ref_audio_strength=ref_audio_strength,
        variant=variant,
        lyric_adherence=lyric_adherence,
        vocal_lora=vocal_lora,
        progress_cb=progress_cb,
    )


def _torch_available() -> bool:
    try:
        import torch  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def gpu_info() -> dict:
    """Report GPU / model status for the UI header."""
    if config.DEMO_MODE:
        return {"mode": "demo", "gpu": None, "model": config.DEFAULT_MODEL}
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            total = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            return {
                "mode": "gpu",
                "gpu": name,
                "vram_gb": round(total, 1),
                "model": config.DEFAULT_MODEL,
                "torch": torch.__version__,
            }
        return {"mode": "cpu", "gpu": None, "model": config.DEFAULT_MODEL}
    except Exception as e:  # noqa: BLE001
        return {"mode": "unavailable", "gpu": None, "error": str(e),
                "model": config.DEFAULT_MODEL}


def _write_demo_tone(path: Path, duration: float = 8.0, seed: int = 0) -> None:
    """Generate a short, harmless sine-sweep WAV so the UI works without a GPU."""
    sr = 44100
    n = int(sr * max(1.0, duration))
    base = 110.0 + (seed % 7) * 20.0  # vary a little by seed
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            t = i / sr
            freq = base * (1.0 + 0.5 * math.sin(2 * math.pi * 0.1 * t))
            env = min(1.0, t * 4) * min(1.0, (duration - t) * 2)
            sample = int(0.25 * env * 32767 * math.sin(2 * math.pi * freq * t))
            frames += struct.pack("<h", max(-32768, min(32767, sample)))
        w.writeframes(bytes(frames))
