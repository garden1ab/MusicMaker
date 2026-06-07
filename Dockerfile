# =============================================================================
# AI Music Studio - Dockerfile
# Base: official PyTorch image with CUDA 12.8 + cuDNN 9.
#
# WHY THIS BASE: The RTX 5080 is a Blackwell GPU (compute capability sm_120).
# Blackwell requires CUDA 12.8+ and PyTorch >= 2.7.0 (the first release shipping
# native sm_120 wheels). Any `pytorch/pytorch:<ver>-cuda12.8-cudnn9-*` tag with
# ver >= 2.7.0 works. Bump PYTORCH_TAG to e.g. 2.9.1 / 2.10.0 / 2.11.0 freely.
# =============================================================================
ARG PYTORCH_TAG=2.8.0-cuda12.8-cudnn9-devel
FROM pytorch/pytorch:${PYTORCH_TAG}

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    # Persist HuggingFace + ACE-Step model downloads onto the mounted volume
    HF_HOME=/data/hf \
    DATA_DIR=/data

# System deps: ffmpeg for audio I/O, git for installing ACE-Step from source.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ffmpeg libsndfile1 build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# 1) Web layer deps
COPY requirements.txt .
RUN pip install -r requirements.txt

# 2) ACE-Step (the music model). Installed from source so we track the latest
#    release. It depends on torch but the base image already provides the
#    correct cu128 build, so pip will not replace it.
RUN pip install "git+https://github.com/ace-step/ACE-Step.git"

# 3) Application code
COPY app ./app
COPY static ./static

# Runtime knobs (override in docker-compose / .env). torch.compile is OFF by
# default: JIT PTX compilation is currently unreliable on Blackwell, and AOT
# kernels in the base image already cover sm_120.
ENV HOST=0.0.0.0 \
    PORT=8000 \
    ACE_MODEL=ACE-Step/ACE-Step-v1-3.5B \
    ACE_DTYPE=bfloat16 \
    ACE_TORCH_COMPILE=false \
    ACE_CPU_OFFLOAD=false \
    ACE_OVERLAPPED_DECODE=true \
    MAX_DURATION=240

EXPOSE 8000
VOLUME ["/data"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
