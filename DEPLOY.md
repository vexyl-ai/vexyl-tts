# Deploying VEXYL-TTS to Google Cloud Run

Complete guide for deploying the VEXYL-TTS server to Google Cloud Run as a serverless container.

VEXYL-TTS is the open-source TTS component from [VEXYL AI](https://vexyl.ai/), the enterprise AI Voice Gateway platform. When deployed to Cloud Run, it provides a scalable, serverless Indian language speech synthesis service that can be used standalone or integrated with the [VEXYL AI Voice Gateway](https://vexyl.ai/) for production telephony workloads.

---

## What Gets Deployed

A single container exposing a single port (8080) with two interfaces:

```
                        ┌──────────────────────────────────────┐
                        │     Cloud Run Container (port 8080)  │
                        │                                      │
  WebSocket clients ──► │  WebSocket  ─► Real-time TTS         │
  (VEXYL, test.html)    │  /           text → audio            │
                        │                                      │
  REST clients ───────► │  POST /batch/synthesize  ─► Async    │
  (curl, apps)          │  GET  /batch/status/{id}    batch    │
                        │  GET  /batch/result/{id}    TTS      │
                        │                                      │
  Health probes ──────► │  GET  /health                        │
                        └──────────────────────────────────────┘
```

- **WebSocket**: Real-time text-to-speech synthesis. Clients send JSON text requests and receive base64-encoded WAV audio.
- **Batch REST API**: Submit text for async synthesis, poll for results with audio.
- **Model**: [ai4bharat/indic-parler-tts](https://huggingface.co/ai4bharat/indic-parler-tts) — supports 17 Indian languages with voice style control.

### Why Cloud Run

- **Scale to zero**: Pay nothing when there's no traffic ($0 idle)
- **Batch API handles cold starts**: Job submission returns instantly with a job ID; the model loads in the background and processes the job
- **asia-south1 (Mumbai)**: Low latency for Indian users

---

## Prerequisites

1. **Google Cloud SDK** installed and authenticated
   ```bash
   gcloud auth login
   gcloud config set project YOUR_PROJECT_ID
   ```

2. **GCP project** with billing enabled

No HuggingFace token needed — the `indic-parler-tts` model is **not gated**.

---

## Quick Deploy

Two commands:

```bash
export GCP_PROJECT_ID=your-gcp-project-id
./deploy.sh
```

The script handles everything: enabling APIs, creating the Artifact Registry, building the Docker image in the cloud, and deploying to Cloud Run. It prints the service URL when done.

---

## What `deploy.sh` Does

### Step 1: Enable GCP APIs

```bash
gcloud services enable cloudbuild.googleapis.com run.googleapis.com artifactregistry.googleapis.com
```

### Step 2: Create Artifact Registry Docker Repository

```bash
gcloud artifacts repositories create vexyl-tts --repository-format=docker --location=asia-south1
```

### Step 3: Build Docker Image via Cloud Build

```bash
gcloud builds submit . --tag=IMAGE_URI --machine-type=e2-highcpu-8 --timeout=3600s
```

Takes **~20-30 minutes** because the image includes PyTorch and downloads the ~4-6 GB model at build time.

### Step 4: Deploy to Cloud Run

Deploys the built image with WebSocket-optimized settings (see configuration table below).

---

## Cloud Run Configuration

| Setting | Value | Why |
|---------|-------|-----|
| `--cpu` | 2 vCPUs | Model inference is CPU-bound |
| `--memory` | 8 GiB | Parler-TTS model needs ~4-6 GB in memory |
| `--timeout` | 3600s (1 hour) | Maximum allowed; needed for long WebSocket sessions |
| `--concurrency` | 50 | Matches `VEXYL_TTS_MAX_CONN` default |
| `--min-instances` | 0 | Scale to zero when idle |
| `--max-instances` | 5 | Cost cap |
| `--cpu-boost` | Enabled | Extra CPU during startup at no extra cost |
| `--session-affinity` | Enabled | WebSocket stickiness |
| `--no-cpu-throttling` | Enabled | CPU stays allocated between requests |
| `--startup-probe-path` | `/health` | Cloud Run checks `/health` for readiness |
| `--startup-probe-failure-threshold` | 18 | Allow up to 180s for model loading + warm-up |
| `--liveness-probe-path` | `/health` | Ongoing health monitoring |
| `--allow-unauthenticated` | Enabled | Access control via application-level API key |

---

## Environment Variables

### Required (for deployment)

| Variable | Description |
|----------|-------------|
| `GCP_PROJECT_ID` | Your Google Cloud project ID |

### Optional (override deploy.sh defaults)

| Variable | Default | Description |
|----------|---------|-------------|
| `GCP_REGION` | `asia-south1` | GCP region (Mumbai) |
| `SERVICE_NAME` | `vexyl-tts` | Cloud Run service name |
| `REPO_NAME` | `vexyl-tts` | Artifact Registry repository name |

### Runtime (set in container / Cloud Run)

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` | Server port (Cloud Run injects this) |
| `VEXYL_TTS_HOST` | `0.0.0.0` | Bind address |
| `VEXYL_TTS_DEVICE` | `cpu` | Inference device |
| `VEXYL_TTS_CACHE_SIZE` | `200` | LRU cache capacity |
| `VEXYL_TTS_MAX_CONN` | `50` | Max concurrent connections |
| `VEXYL_TTS_API_KEY` | _(empty)_ | Shared secret for API key auth |

---

## API Key Authentication

By default, any client that knows the Cloud Run URL can connect. To restrict access, set `VEXYL_TTS_API_KEY`.

### How it works

- Client sends the key as an `X-API-Key` HTTP header
- Server validates using timing-safe comparison (`hmac.compare_digest`)
- If missing or wrong → **HTTP 403 Forbidden**
- `/health` is **exempt** — probes always work without a key
- When not set, all connections are allowed

### Setting the key on Cloud Run

```bash
export API_KEY=$(openssl rand -base64 32)
gcloud run services update vexyl-tts \
    --region=asia-south1 \
    --set-env-vars VEXYL_TTS_API_KEY=$API_KEY
echo "VEXYL_TTS_API_KEY=$API_KEY"
```

### Verifying

```bash
# Health check — works without a key
curl https://vexyl-tts-XXXX-el.a.run.app/health

# WebSocket without key — should get 403
wscat -c wss://vexyl-tts-XXXX-el.a.run.app

# WebSocket with key — should connect
wscat -c wss://vexyl-tts-XXXX-el.a.run.app -H "X-API-Key: your-key"
```

---

## Post-Deployment Verification

### 1. Health check

```bash
curl https://vexyl-tts-XXXX-el.a.run.app/health
```

### 2. Batch API test

```bash
# Submit
curl -X POST https://vexyl-tts-XXXX-el.a.run.app/batch/synthesize \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{"text":"नमस्ते दुनिया","lang":"hi-IN","style":"default"}'

# Poll (replace with actual job_id)
curl https://vexyl-tts-XXXX-el.a.run.app/batch/status/batch_a1b2c3d4 \
  -H "X-API-Key: your-key"
```

### 3. WebSocket test

Open `test.html` in a browser, update the WebSocket URL, and test.

---

## Batch API Reference

### POST /batch/synthesize

Submit text for asynchronous synthesis.

**Request**: `application/json`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `text` | string | Yes | Text to synthesize (max 5,000 chars) |
| `lang` | string | No | Language code (default: `ml-IN`) |
| `style` | string | No | Voice style (default: `default`) |

**Response** (201 Created):

```json
{
  "job_id": "batch_a1b2c3d4e5f6g7h8",
  "status": "queued",
  "language": "hi-IN",
  "style": "default",
  "text_length": 14
}
```

### GET /batch/status/{job_id}

**When completed** (200):

```json
{
  "job_id": "batch_a1b2c3d4e5f6g7h8",
  "status": "completed",
  "language": "hi-IN",
  "style": "default",
  "audio_b64": "UklGR...",
  "sample_rate": 22050,
  "latency_ms": 2400
}
```

### GET /batch/result/{job_id}

Returns 202 if processing, 200 when complete with audio.

### Error Codes

| Code | Condition |
|------|-----------|
| 400 | Missing text, text too long, invalid JSON, wrong Content-Type |
| 403 | Invalid or missing API key |
| 404 | Job not found |
| 413 | Request body too large |
| 429 | Too many pending jobs (max 1,000) |

---

## Docker Image Details

| Layer | Size (approx) | Purpose |
|-------|---------------|---------|
| `python:3.11-slim` base | ~150 MB | Minimal Python runtime |
| System deps (`libgomp1`, `libsndfile1`) | ~20 MB | OpenMP threading, audio I/O |
| PyTorch CPU | ~800 MB | Inference engine |
| Python dependencies | ~300 MB | parler-tts, transformers, etc. |
| TTS model | ~4-6 GB | Baked in at build time |
| **Total** | **~5-7 GB** | |

---

## Cost Analysis

### Per-Request Cost

For a single synthesis request that takes 15 seconds on a 2-vCPU / 8-GiB instance:

| Resource | Calculation | Cost |
|----------|------------|------|
| CPU | 2 vCPU x 15s x $0.000024 | $0.00072 |
| Memory | 8 GiB x 15s x $0.0000025 | $0.00030 |
| **Total per request** | | **~$0.001** |

### Monthly Cost Estimates

| Usage | Requests/month | Estimated cost |
|-------|---------------|---------------|
| Light (testing) | ~100 | **~$0.10** |
| Medium (internal) | ~1,000 | **~$1.00** |
| Heavy (production) | ~10,000 | **~$10.00** |
| Always-warm (min-instances=1) | any | **~$80-100/month** |

---

## Troubleshooting

### Cold start timeout

- Startup probe allows 180s (18 x 10s). Increase if needed:
  ```
  --startup-probe-failure-threshold=24    # 240s
  ```

### Out of memory

- Default 8 GiB should be sufficient. If OOM:
  ```bash
  gcloud run services update vexyl-tts --region=asia-south1 --memory=16Gi
  ```

### 403 Forbidden

- Check `X-API-Key` header matches `VEXYL_TTS_API_KEY` exactly
- `/health` is exempt — if health works but others return 403, it's a key mismatch
