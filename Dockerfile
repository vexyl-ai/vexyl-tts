FROM python:3.11-slim

# System deps: libgomp1 for PyTorch OpenMP, libsndfile1 for soundfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgomp1 libsndfile1 git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install PyTorch CPU-only (before other deps to cache this large layer).
# torchaudio MUST be pinned here too, from the same CPU-only index — otherwise
# `pip install -r requirements.txt` below pulls it in later as a transitive
# dependency of parler-tts -> audiotools -> dac from the default PyPI index,
# which gives a torchaudio build whose native extension doesn't match this
# torch build and fails to load at import time:
#   OSError: Could not load this library: .../torchaudio/lib/_torchaudio.abi3.so
RUN pip install --no-cache-dir \
    torch torchaudio \
    --index-url https://download.pytorch.org/whl/cpu

# Install remaining Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download the model at build time (baked into image, ~4-6GB).
# ai4bharat/indic-parler-tts IS a gated repo on Hugging Face (despite the comment
# that used to be here) — needs an authenticated, approved token or the download
# 401s. The token is only needed for THIS build step, so scope it to the RUN via
# an inline env var. Do NOT use `ENV HF_TOKEN=...`: that persists the secret into
# the final image config, leaking it to anyone who runs `docker inspect`/`docker
# history` or pulls the image — and the token has no runtime purpose (model is
# already baked in). ARG is not referenced elsewhere, so it stays out of the
# final image env. huggingface_hub picks up HF_TOKEN automatically, so no code
# changes are needed in the from_pretrained calls below.
ARG HF_TOKEN
RUN HF_TOKEN=${HF_TOKEN} python -c "\
from parler_tts import ParlerTTSForConditionalGeneration; \
from transformers import AutoTokenizer; \
model = ParlerTTSForConditionalGeneration.from_pretrained('ai4bharat/indic-parler-tts'); \
AutoTokenizer.from_pretrained('ai4bharat/indic-parler-tts'); \
AutoTokenizer.from_pretrained(model.config.text_encoder._name_or_path)"

# Copy application code
COPY vexyl_tts_server.py .

# Cloud Run injects PORT; set defaults for local testing
ENV PORT=8080 \
    VEXYL_TTS_HOST=0.0.0.0 \
    VEXYL_TTS_DEVICE=cpu

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health')"

CMD ["python", "-u", "vexyl_tts_server.py"]
