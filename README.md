<p align="center">
  <a href="https://vexyl.ai/">
    <img src="https://vexyl.ai/wp-content/themes/theme/assets/images/logo.png" alt="VEXYL AI" width="200">
  </a>
</p>

<h1 align="center">VEXYL-TTS</h1>

<p align="center"><strong>Open-source Indian language text-to-speech server</strong></p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10%2B-green.svg" alt="Python 3.10+"></a>
  <a href="#supported-languages"><img src="https://img.shields.io/badge/Languages-22-orange.svg" alt="Languages"></a>
</p>

WebSocket + REST text-to-speech server wrapping the [ai4bharat/indic-parler-tts](https://huggingface.co/ai4bharat/indic-parler-tts) model. Self-hosted, zero API costs, full data sovereignty. Supports 22 Indian languages with 69 pre-built voices and emotion/tone control.

Built by [VEXYL AI](https://vexyl.ai/) — the team behind the **AI Voice Gateway**, an enterprise platform that bridges telephony (PSTN, SIP, Asterisk, WebRTC) with LLMs and AI services. VEXYL-TTS is the open-source TTS component, extracted for standalone use and community contribution.

---

## Overview

VEXYL-TTS provides two synthesis modes on a single port:

- **Real-time WebSocket** — Send JSON text requests, receive base64-encoded WAV audio responses with latency tracking
- **Batch synthesis** — REST API for async text-to-speech. Submit text, poll for results

### Features

- 22 Indian languages supported
- Named speaker selection per language (44 speakers total)
- Voice presets with tone/style control (calm, warm, formal)
- Custom voice description override for any speaker + tone combination
- In-memory LRU cache for repeated phrases
- WebSocket streaming + batch REST API on the same port
- API key authentication (optional)
- Docker and Cloud Run ready
- Browser test clients included

---

## Supported Languages

| Code | Language | Code | Language |
|------|----------|------|----------|
| `ml-IN` | Malayalam | `pa-IN` | Punjabi |
| `hi-IN` | Hindi | `or-IN` | Odia |
| `ta-IN` | Tamil | `as-IN` | Assamese |
| `te-IN` | Telugu | `ur-IN` | Urdu |
| `kn-IN` | Kannada | `ne-IN` | Nepali |
| `bn-IN` | Bengali | `sa-IN` | Sanskrit |
| `gu-IN` | Gujarati | `brx-IN` | Bodo |
| `mr-IN` | Marathi | `doi-IN` | Dogri |
| `en-IN` | English (Indian) | `kok-IN` | Konkani |
| `en-US` | English (US) | `mai-IN` | Maithili |
| `en-GB` | English (UK) | `mni-IN` | Manipuri |
|          |          | `sat-IN` | Santali |
|          |          | `sd-IN` | Sindhi |

---

## Quick Start

```bash
# 1. Run the automated setup (one command)
./setup.sh

# 2. Start the server
./run.sh

# 3. Test in browser
open test.html
```

### Prerequisites

- **Python 3.10+**
- **macOS or Linux**
- **~6 GB disk space** for model weights and dependencies
- **NVIDIA GPU (optional)** — automatically detected by `setup.sh`. Installs CUDA-enabled PyTorch and sets `VEXYL_TTS_DEVICE=auto`

The model is **not gated** — no HuggingFace login required. The setup script handles everything: creates a virtual environment, detects GPU, installs the correct PyTorch (CPU or CUDA), downloads the model, and generates config files.

---

## Manual Setup

### 1. Create virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
```

### 2. Install dependencies

```bash
# PyTorch — choose ONE:
pip install torch --index-url https://download.pytorch.org/whl/cpu      # CPU-only
pip install torch --index-url https://download.pytorch.org/whl/cu128    # NVIDIA GPU (CUDA 12.8+)
pip install torch --index-url https://download.pytorch.org/whl/cu126    # NVIDIA GPU (CUDA 12.6)
pip install torch --index-url https://download.pytorch.org/whl/cu124    # NVIDIA GPU (CUDA 12.4)
pip install torch --index-url https://download.pytorch.org/whl/cu121    # NVIDIA GPU (CUDA 12.1)

# Parler-TTS + other dependencies
pip install git+https://github.com/huggingface/parler-tts.git
pip install transformers websockets numpy soundfile
```

### 3. Download the model

```bash
python3 -c "
from parler_tts import ParlerTTSForConditionalGeneration
from transformers import AutoTokenizer
model = ParlerTTSForConditionalGeneration.from_pretrained('ai4bharat/indic-parler-tts')
AutoTokenizer.from_pretrained('ai4bharat/indic-parler-tts')
AutoTokenizer.from_pretrained(model.config.text_encoder._name_or_path)
"
```

### 4. Create `.env`

```bash
VEXYL_TTS_HOST=127.0.0.1
VEXYL_TTS_PORT=8092
VEXYL_TTS_DEVICE=auto
VEXYL_TTS_CACHE_SIZE=200
VEXYL_TTS_SAMPLE_RATE=8000
# VEXYL_TTS_API_KEY=your-secret-here
```

### 5. Start the server

```bash
source venv/bin/activate
export $(grep -v '^#' .env | xargs)
python3 vexyl_tts_server.py
```

---

## Configuration

### Environment Variables

| Variable | Default | Options | Description |
|----------|---------|---------|-------------|
| `VEXYL_TTS_HOST` | `0.0.0.0` | Any IP | Bind address. Use `127.0.0.1` for local-only |
| `VEXYL_TTS_PORT` | `8080` | Any port | Port number (via `PORT` or `VEXYL_TTS_PORT`). The sample `.env` uses `8092` |
| `VEXYL_TTS_DEVICE` | `auto` | `auto`, `cpu`, `cuda`, `mps` | Inference device. `auto` detects CUDA/MPS if available |
| `VEXYL_TTS_CACHE_SIZE` | `200` | Any integer | LRU cache capacity for synthesized audio |
| `VEXYL_TTS_MAX_CONN` | `50` | Any integer | Max concurrent WebSocket connections |
| `VEXYL_TTS_SAMPLE_RATE` | `0` | `0`, `8000`, `16000`, etc. | Output sample rate. `0` = native (44100Hz). Set `8000` for Asterisk/telephony |
| `VEXYL_TTS_API_KEY` | _(empty)_ | Any string | Shared secret for authentication. Clients must send `X-API-Key` header |

### API Key Authentication

Set `VEXYL_TTS_API_KEY` on both server and client. The client sends the key as an `X-API-Key` header. The `/health` endpoint is always exempt. When the variable is empty, authentication is disabled.

```bash
# Server .env
VEXYL_TTS_API_KEY=your-shared-secret

# Test with wscat
wscat -c ws://127.0.0.1:8092 -H "X-API-Key: your-shared-secret"
```

---

## API Reference

### WebSocket Protocol

```
Client                              Server
  |                                    |
  |<---- {"type":"ready"} -------------|  (immediate on connect)
  |-- {"type":"synthesize",...} ------>|  (send text for synthesis)
  |<---- {"type":"audio",...} ---------|  (receive audio response)
  |-- {"type":"get_stats"} ---------->|  (request cache stats)
  |<---- {"type":"stats",...} ---------|
  |-- {"type":"ping"} --------------->|
  |<---- {"type":"pong"} -------------|
```

#### Client -> Server

| Message | Description |
|---------|-------------|
| `{"type":"synthesize","text":"...","lang":"ml-IN","style":"default","request_id":"x"}` | Synthesize text to audio. Optional `"description"` field overrides the voice preset (see [Speakers](#speakers)) |
| `{"type":"get_stats"}` | Request cache statistics |
| `{"type":"ping"}` | Keepalive |

#### Server -> Client

| Message | Description |
|---------|-------------|
| `{"type":"ready","model":"indic-parler-tts","sample_rate":22050,"languages":[...]}` | Server loaded, ready |
| `{"type":"audio","request_id":"x","audio_b64":"...","sample_rate":22050,"cached":false,"latency_ms":2400}` | Synthesized audio |
| `{"type":"stats","cache_size":N,"cache_hits":N,"cache_total":N,"hit_rate":N}` | Cache statistics |
| `{"type":"pong"}` | Keepalive response |
| `{"type":"error","message":"..."}` | Error |

#### Voice Styles

| Style | Description |
|-------|-------------|
| `default` | Calm, clear, professional tone (female speaker) |
| `warm` | Warm, empathetic tone for healthcare (female speaker) |
| `formal` | Formal, neutral tone with precise diction (male speaker) |

All 22 languages support all 3 styles. Each style uses a specific named speaker from the model's trained embeddings.

#### Speakers

Each language has named speakers from the `ai4bharat/indic-parler-tts` model. The `style` field selects the speaker automatically (default/warm = female, formal = male). To use a specific speaker with any tone, pass a custom `description` field:

```json
{"type":"synthesize","text":"Hello","lang":"ml-IN","style":"default","description":"Harish speaks in a warm and friendly tone. The recording is of very high quality with no background noise.","request_id":"1"}
```

| Language | Female Speaker | Male Speaker |
|----------|---------------|-------------|
| Malayalam (ml-IN) | Anjali | Harish |
| Hindi (hi-IN) | Divya | Rohit |
| Tamil (ta-IN) | Kavitha | Jaya* |
| Telugu (te-IN) | Lalitha | Prakash |
| Kannada (kn-IN) | Anu | Suresh |
| Bengali (bn-IN) | Aditi | Arjun |
| Gujarati (gu-IN) | Neha | Yash |
| Marathi (mr-IN) | Sunita | Sanjay |
| English (en-IN) | Mary | Thoma |
| Punjabi (pa-IN) | Divjot | Gurpreet |
| Odia (or-IN) | Debjani | Manas |
| Assamese (as-IN) | Sita | Amit |
| Urdu (ur-IN) | Zainab | Rohit |
| Nepali (ne-IN) | Amrita | Ram |
| Sanskrit (sa-IN) | Vasudha | Aryan |
| Bodo (brx-IN) | Bimala | Bikram |
| Dogri (doi-IN) | Meena | Vikram |
| Konkani (kok-IN) | Priya | Kaustubh |
| Maithili (mai-IN) | Shruti | Saurabh |
| Manipuri (mni-IN) | Leima | Tomba |
| Santali (sat-IN) | Sumitra | Raju |
| Sindhi (sd-IN) | Hema | Mohan |

*Tamil: Jaya is female — used in the `formal` style preset.

### Batch API

```
POST /batch/synthesize       -> submit text for synthesis
GET  /batch/status/{job_id}  -> check job status + get audio when done
GET  /batch/result/{job_id}  -> get audio (202 if not ready)
GET  /health                 -> health check
```

#### Submit — `POST /batch/synthesize`

```bash
curl -X POST http://localhost:8092/batch/synthesize \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-secret" \
  -d '{"text":"नमस्ते दुनिया","lang":"hi-IN","style":"default"}'
```

| Field | Required | Description |
|-------|----------|-------------|
| `text` | Yes | Text to synthesize (max 5,000 chars) |
| `lang` | No | Language code (default: `ml-IN`). See [Supported Languages](#supported-languages) |
| `style` | No | Voice style: `default`, `warm`, or `formal` (default: `default`) |
| `description` | No | Custom voice description to override the style preset. Use a specific speaker name with tone (see [Speakers](#speakers)) |

Response (201):
```json
{"job_id": "batch_a1b2c3d4", "status": "queued", "language": "hi-IN", "style": "default", "text_length": 14}
```

#### Status — `GET /batch/status/{job_id}`

Returns job status with audio when completed.

#### Result — `GET /batch/result/{job_id}`

Returns 202 if processing, 200 when complete with `audio_b64` field.

#### Limits

| Limit | Value |
|-------|-------|
| Max text length | 5,000 characters |
| Max pending jobs | 1,000 |
| Job TTL | 1 hour |

### Health Endpoint

```bash
curl http://127.0.0.1:8092/health
```

```json
{
  "status": "ok",
  "model": "indic-parler-tts",
  "device": "cuda",
  "cache_size": 42,
  "cache_capacity": 200,
  "cache_hit_rate": 65.3,
  "active_connections": 0,
  "max_connections": 50,
  "uptime_seconds": 3600.5,
  "batch_jobs_queued": 0,
  "batch_jobs_total": 0
}
```

---

## Browser Test Clients

### `test.html` — Real-time WebSocket TTS

Open directly in a browser. Select language, style, and speaker, connect to WebSocket, type text and synthesize. Audio plays in real time. The speaker dropdown updates dynamically per language — choose "Auto" to let the style pick the speaker, or select a specific speaker to override.

### `test-batch.html` — Batch TTS

Submit text for async batch synthesis with language, style, and speaker selection. Poll for results and play the resulting audio. Same speaker override support as the WebSocket client.

---

## Docker

### CPU Build

```bash
docker build -t vexyl-tts .
docker run -p 8080:8080 vexyl-tts
```

### GPU Build

```bash
docker build -f Dockerfile.gpu -t vexyl-tts-gpu .
docker run --gpus all -p 8080:8080 vexyl-tts-gpu
```

Requires [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) for `--gpus all`.

### With API Key

```bash
docker run -p 8080:8080 -e VEXYL_TTS_API_KEY=mysecret vexyl-tts
```

---

## Cloud Run Deployment

See [DEPLOY.md](DEPLOY.md) for a complete guide.

Quick deploy:

```bash
export GCP_PROJECT_ID=your-project-id
./deploy.sh
```

No HuggingFace token needed — the model is not gated.

---

## VEXYL AI Voice Gateway

[VEXYL AI Voice Gateway](https://vexyl.ai/) is an enterprise platform that connects phone calls directly to AI — bridging traditional telephony (PSTN, SIP, Asterisk, WebRTC) with LLMs, STT, and TTS providers. It supports 22+ AI providers including OpenAI, Groq, Deepgram, and ElevenLabs, with sub-200ms latency and features like barge-in, human escalation, and outbound calling.

VEXYL-TTS plugs into the Voice Gateway as a self-hosted TTS provider, giving you Indian language speech synthesis with zero external API calls — ideal for data sovereignty, cost control, or as a fallback when cloud TTS providers are unavailable.

**Key benefits of using VEXYL-TTS with the Voice Gateway:**
- **Zero API cost** for Indian language calls — no per-character TTS billing
- **Full data sovereignty** — text never leaves your infrastructure
- **Fallback resilience** — automatic failover from cloud TTS to local model
- **Low latency** — same-machine WebSocket connection, no network round-trip
- **Voice control** — style presets (calm, warm, formal) tuned for healthcare IVR

Visit [vexyl.ai](https://vexyl.ai/) to learn more about the enterprise product.

See `tts-provider-patch.md` and `language-config-patch.md` for Voice Gateway integration instructions.

---

## Production

### PM2

```bash
pm2 start run.sh --name vexyl-tts
pm2 logs vexyl-tts
pm2 save && pm2 startup
```

### GPU Acceleration

The `setup.sh` script auto-detects NVIDIA GPUs and installs the correct CUDA-enabled PyTorch. If you set up manually:

```bash
source venv/bin/activate
pip uninstall torch -y
pip install torch --index-url https://download.pytorch.org/whl/cu128  # Match your CUDA version
```

Set `VEXYL_TTS_DEVICE=auto` (or `cuda`) in `.env` and restart.

#### GPU Performance Optimizations (v1.1.0)

The server includes several GPU-specific optimizations enabled automatically:

- **FP16 inference** — model runs in half-precision, reducing VRAM usage and improving throughput
- **SDPA (Scaled Dot-Product Attention)** — PyTorch's native optimized attention on the 24-layer decoder
- **Flash Attention 2** — auto-enabled when `flash-attn` package is installed (optional, further ~10-20% speedup)
- **Pre-cached voice tokens** — all 69 voice descriptions are tokenized once at startup and kept on GPU
- **LRU cache on all paths** — both WebSocket and batch API cache synthesized audio; repeated text returns in ~1ms

#### Typical Latency (RTX 5070, FP16, 8kHz output)

| Text Length | Inference Time |
|------------|---------------|
| 5 chars | ~980ms |
| 43 chars | ~1,350ms |
| 100 chars | ~2,850ms |
| 254 chars | ~6,600ms |
| Cached (any) | ~1ms |

The server logs a detailed per-request timing breakdown:
```
[perf] tokenize=1.6ms | inference=1347ms | gpu→cpu=8.8ms | resample=0.6ms | wav_encode=0.2ms | total=1364ms | text=43chars
```

### macOS Metal (MPS)

On Apple Silicon (M1/M2/M3/M4), `VEXYL_TTS_DEVICE=auto` will automatically detect and use MPS acceleration. The server includes a built-in workaround for the MPS conv1d channel limit — the audio decoder runs on CPU while the rest of the model uses the GPU.

### Asterisk / Telephony (8kHz)

For Asterisk and telephony systems that expect 8kHz audio:

```bash
# .env
VEXYL_TTS_SAMPLE_RATE=8000
```

The model generates at 44100Hz natively and downsamples to 8000Hz before encoding the WAV. This produces smaller audio files directly compatible with G.711 (ulaw/alaw) codecs.

---

## Troubleshooting

### Port already in use

```bash
lsof -i :8092
# Or change port: VEXYL_TTS_PORT=8093
```

### No audio output

- Check text is not empty
- Check language code is valid (see supported languages)
- Check server logs for synthesis errors

### WebSocket connection refused

- Ensure the server is running: `./run.sh`
- Check host/port match between client and `.env`
- For remote access, set `VEXYL_TTS_HOST=0.0.0.0`

### Out of memory

The Parler-TTS model needs ~4-6 GB RAM (CPU) or ~3-4 GB VRAM (GPU with FP16). Ensure sufficient memory or use CPU mode (`VEXYL_TTS_DEVICE=cpu`).

### Flash Attention build fails

`flash-attn` requires the CUDA toolkit version to match PyTorch's CUDA version exactly. If your system CUDA toolkit differs (e.g., CUDA 13.0 with PyTorch cu128), the build will fail. This is optional — the server falls back to SDPA which is nearly as fast.

---

## Project Files

| File | Description |
|------|-------------|
| `vexyl_tts_server.py` | Python server — WebSocket TTS + batch REST API |
| `setup.sh` | Automated setup — venv, deps, model download |
| `run.sh` | Start script — loads `.env`, activates venv, launches server |
| `deploy.sh` | One-command Cloud Run deployment |
| `Dockerfile` | Container image with baked-in model (CPU) |
| `Dockerfile.gpu` | GPU container image (NVIDIA CUDA 12.8) |
| `CHANGELOG.md` | Version history and release notes |
| `.env.example` | Template for server configuration |
| `test.html` | Browser test client for real-time TTS |
| `test-batch.html` | Browser test client for batch API |
| `tts-provider-patch.md` | Voice Gateway `tts-provider.js` integration guide |
| `language-config-patch.md` | Voice Gateway `language-config.js` integration guide |

---

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

---

## License

[Apache License 2.0](LICENSE) — Copyright 2025-2026 VEXYL AI
