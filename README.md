# 🎵 AI Music Studio

A self-hosted, Dockerized AI music generation tool built around **ACE-Step 1.5** — an open-source (Apache-2.0) music foundation model. Generate full instrumental or vocal tracks from a free-text prompt *or* from a structured genre builder, build new music from an uploaded reference clip, and control duration, instruments, energy, tempo, key, structure, and genre blending — all from a single web UI.

Designed to run on a single consumer GPU. Tested target: **NVIDIA RTX 5080 (16 GB)** with 128 GB system RAM.

---

## Why ACE-Step?

It's the best fit for "good quality, fully local, fits in 16 GB, commercially usable":

- **Apache-2.0 license** — output is yours to use commercially (unlike MusicGen's non-commercial license).
- **Fast** — generates roughly a minute of audio in a few seconds on an RTX 4090/3090-class card; the 3.5B model runs in well under 16 GB (and can be squeezed to ~8 GB with CPU offload).
- **The right controls** — it's tag/description driven and natively supports instruments, style blending, song structure, duration, and **audio2audio** (generating from a reference clip), which maps cleanly onto every control you asked for.

The app translates the structured UI controls (genre + sub-genre + instruments + energy + tempo + key + structure + blend) into an optimal ACE-Step tag string behind the scenes, so you get fine-grained control without writing prompts by hand.

---

## Requirements

- A Linux host (or WSL2) with an NVIDIA GPU and recent drivers (CUDA 12.8-capable; required for Blackwell/RTX 50-series).
- **Docker** + **Docker Compose**.
- **NVIDIA Container Toolkit** installed on the host so containers can see the GPU:

```bash
# Ubuntu install of the NVIDIA Container Toolkit
distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Verify the GPU is visible to Docker:

```bash
docker run --rm --gpus all pytorch/pytorch:2.8.0-cuda12.8-cudnn9-devel \
  python -c "import torch; print(torch.cuda.get_device_name(0))"
```

You should see `NVIDIA GeForce RTX 5080`.

---

## Quick start

```bash
cp .env.example .env          # optional: tweak settings
docker compose up --build
```

Then open **http://localhost:8000**.

The first generation downloads the ACE-Step checkpoint (a few GB) into `./data/checkpoints`, so it persists across restarts.

### Try it with no GPU first

Want to click through the whole interface on a laptop? Run in demo mode — it serves a placeholder tone instead of loading the model:

```bash
DEMO_MODE=1 docker compose up --build
# or locally, without Docker:
pip install -r requirements.txt
DEMO_MODE=1 DATA_DIR=./data uvicorn app.main:app --reload
```

---

## Using the studio

**Two ways to start a track:**

- **Genre Builder** — pick a genre and sub-genre, optionally blend in a second genre with a strength slider.
- **Text Prompt** — describe the music in plain language.

**Shared controls (apply to both modes):**

| Control | What it does |
|---|---|
| Instruments | Tap chips to force specific instrumentation |
| Energy | 0–100 slider mapped to dynamics descriptors |
| Tempo | BPM slider (50–200) plus quick feel presets |
| Key | Musical key (e.g. *A minor*) |
| Structure | Tap blocks (intro, verse, chorus, drop…) in order |
| Instrumental | Toggle vocals on/off |
| Duration | Up to `MAX_DURATION` seconds |
| Build from a clip | Upload audio for **audio2audio**; the strength slider controls how closely the output follows it |
| Advanced | Seed, quality (sampling steps), guidance scale, extra tags |

### Vocals & voice

Flip on **Add vocals** to open the vocals panel:

- **Lyrics** — type your own, using `[verse]`/`[chorus]`/`[bridge]` tags on their own lines (the *insert structure* button scaffolds them from your chosen structure blocks). Leave it blank and the model improvises vocals.
- **Voice** — female / male / androgynous / choir / child.
- **Vocal style** — stackable tags like soulful, raspy, falsetto, operatic, rap, breathy, autotuned…
- **Language** — ACE-Step handles ~10 languages well.
- **Lyric adherence** — how tightly the melody hugs your exact words.

**Voice cloning / matching.** In the *Reference clip* panel, switch the role to **Clone / match voice** and upload a singing clip. The open ACE-Step model does this *zero-shot*: it carries the reference singer's timbre into the generated vocals via its audio-conditioning path (turn the "match voice strength" up for a closer match). This is reference-based voice *matching* — good for demos and same-voice consistency, but it is not studio-grade cloning. For high-fidelity cloning of a specific voice you'd train a LoRA on that voice (see ACE-Step's `TRAIN_INSTRUCTION.md`) or use a dedicated vocal-synth tool.

> ⚠️ **Use voices you have the right to.** The app requires you to confirm the uploaded voice is your own or used with the singer's consent. Don't clone real artists to impersonate them — it's very likely a violation of publicity/likeness rights and platform rules.

Hit **Generate**, watch the oscilloscope, then play or download the resulting `.wav`.

---

## Configuration

All settings are environment variables (see `.env.example`). The most useful:

- `ACE_MODEL` — model checkpoint. Default `ACE-Step/ACE-Step-v1-3.5B` (best fit for 16 GB). To use the higher-quality XL (4B) model, set it here and enable `ACE_CPU_OFFLOAD=true`.
- `ACE_CPU_OFFLOAD` — set `true` if you hit out-of-memory; runs in as little as ~8 GB VRAM at the cost of speed.
- `ACE_OVERLAPPED_DECODE` — `true` speeds up decoding (default on).
- `ACE_TORCH_COMPILE` — left **off** on purpose: JIT PTX compilation is currently unreliable on Blackwell (sm_120). The base image's ahead-of-time kernels already cover the RTX 5080.
- `PYTORCH_TAG` — the base image. Default `2.8.0-cuda12.8-cudnn9-devel`. Any `>=2.7.0` `-cuda12.8-` tag works (2.9.1, 2.10.0, 2.11.0…).

---

## A note on the RTX 5080 / Blackwell

Blackwell GPUs report compute capability **sm_120** and need **CUDA 12.8+** with **PyTorch ≥ 2.7.0** (the first release with native sm_120 wheels). Older PyTorch builds throw `sm_120 is not compatible with the current PyTorch installation` and fall back to CPU or crash. This project sidesteps that entirely by basing the image on `pytorch/pytorch:*-cuda12.8-cudnn9-*`, which ships the correct cu128 build.

---

## Architecture

```
ai-music-studio/
├── docker-compose.yml      # GPU reservation, volumes, ports
├── Dockerfile              # Blackwell-ready (CUDA 12.8 / PyTorch 2.8) image
├── requirements.txt
├── .env.example
├── app/
│   ├── main.py             # FastAPI: routes + single-worker job queue
│   ├── prompt_composer.py  # structured controls -> ACE-Step tag string
│   ├── pipeline.py         # ACE-Step wrapper (lazy load, version-defensive)
│   ├── schemas.py          # request/response models
│   └── config.py           # env-driven settings
└── static/                 # vanilla HTML/CSS/JS UI (no build step)
```

Generations run one-at-a-time through a single background worker, which is the right model for one GPU (no VRAM contention). Jobs are submitted via `POST /api/generate`, polled via `GET /api/jobs/{id}`, and the audio is served from `GET /api/audio/{id}`.

---

## License & responsible use

The application code here is provided as-is. ACE-Step itself is Apache-2.0. As the ACE-Step authors note, verify the originality of generated works, disclose AI involvement where appropriate, and obtain permissions when adapting protected styles. You are responsible for how you use generated audio.
