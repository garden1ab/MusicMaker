"""Pydantic models for the API."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    # Mode
    mode: str = Field("genre", description="'genre' or 'text'")
    text_prompt: Optional[str] = None

    # Genre controls
    genre: Optional[str] = None
    subgenre: Optional[str] = None
    blend_genre: Optional[str] = None
    blend_amount: int = 0

    # Shared musical controls
    instruments: list[str] = Field(default_factory=list)
    energy: Optional[int] = 50            # 0-100
    tempo: Optional[str] = None           # bpm number (as str) or named feel
    key: Optional[str] = None
    structure: list[str] = Field(default_factory=list)
    instrumental: bool = True
    extra_tags: Optional[str] = None

    # Vocals
    lyrics: Optional[str] = None
    vocal_gender: Optional[str] = None
    vocal_styles: list[str] = Field(default_factory=list)
    language: Optional[str] = None
    lyric_adherence: Optional[float] = None   # maps to guidance_scale_lyric
    vocal_lora: Optional[str] = None          # optional Lyric2Vocal LoRA path/id

    # Output controls
    duration: float = 60.0                # seconds
    seed: Optional[int] = None

    # Quality / model
    model_variant: Optional[str] = None   # override default model
    infer_steps: int = 60
    guidance_scale: float = 15.0

    # Reference clip (build-from / voice cloning)
    ref_audio_id: Optional[str] = None    # id returned by /api/upload
    ref_audio_strength: float = 0.5       # 0 = ignore ref, 1 = stay very close
    ref_role: str = "music"               # "music" | "voice"
    clone_consent: bool = False           # required when ref_role == "voice"


class GenerateResponse(BaseModel):
    job_id: str
    status: str


class JobStatus(BaseModel):
    job_id: str
    status: str                            # queued | running | done | error
    progress: float = 0.0
    message: str = ""
    audio_url: Optional[str] = None
    prompt_used: Optional[str] = None
    lyrics_used: Optional[str] = None
    duration: Optional[float] = None
    seed: Optional[int] = None
    error: Optional[str] = None


class UploadResponse(BaseModel):
    ref_audio_id: str
    filename: str
    duration: Optional[float] = None
