FROM python:3.11-slim

# System deps: libgomp1 for PyTorch OpenMP, libsndfile1 for soundfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgomp1 libsndfile1 git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install PyTorch CPU-only (before other deps to cache this large layer)
RUN pip install --no-cache-dir \
    torch \
    --index-url https://download.pytorch.org/whl/cpu

# Install remaining Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download the model at build time (baked into image, ~4-6GB)
# indic-parler-tts is NOT gated — no HF token needed
RUN python -c "\
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
