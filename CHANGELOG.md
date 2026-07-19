# Changelog

## v1.1.0 — GPU Support & Performance (2026-03-25)

### GPU Auto-Detection in Setup
- `setup.sh` now detects NVIDIA GPUs via `nvidia-smi` and installs the correct CUDA-enabled PyTorch automatically
- Maps CUDA version to the right PyTorch wheel (cu118 / cu121 / cu124 / cu126 / cu128)
- Falls back to CPU-only PyTorch gracefully when no GPU is found
- Installs `python3-dev` (needed for Triton/torch.compile) on GPU systems
- Installs `flash-attn` build dependencies (wheel, psutil, ninja, packaging) on GPU systems
- `.env` now defaults to `VEXYL_TTS_DEVICE=auto` on GPU systems instead of hardcoded `cpu`
- Setup summary now displays detected GPU name, VRAM, and CUDA variant

### GPU Dockerfile
- Added `Dockerfile.gpu` based on `nvidia/cuda:12.8.0-runtime-ubuntu22.04`
- Installs PyTorch with CUDA 12.8 support, sets `VEXYL_TTS_DEVICE=auto`
- Run with: `docker run --gpus all -p 8080:8080 vexyl-tts-gpu`

### Inference Performance
- **FP16 inference** — model loads with `torch_dtype=torch.float16` (previously FP32)
- **`torch.inference_mode()`** — replaced `torch.no_grad()` for faster inference (disables autograd version tracking)
- **Pre-cached voice description tokens** — all 69 voice preset descriptions are tokenized once at startup and kept on GPU, saving ~6-8ms per request
- **Flash Attention 2 support** — server auto-detects and enables FA2 on the 24-layer decoder when `flash-attn` is installed (falls back to SDPA)
- **Post-processing outside inference lock** — normalization, resampling, and WAV encoding no longer block the GPU, improving throughput under concurrent load

### Batch API Cache Support
- Batch synthesis worker (`POST /batch/synthesize`) now uses the LRU audio cache
- Previously only WebSocket requests benefited from caching; repeated batch requests bypassed it entirely
- Repeated text now returns in ~1ms instead of full re-synthesis

### Performance Logging
- Each synthesis call now logs a detailed timing breakdown:
  ```
  [perf] tokenize=1.6ms | inference=1347ms | gpu→cpu=8.8ms | resample=0.6ms | wav_encode=0.2ms | total=1364ms | text=43chars
  ```
- Shows exactly where time is spent: tokenization, model inference, GPU-to-CPU transfer, resampling, and WAV encoding

### Warm-Up
- Server now runs two warm-up inferences at startup (short + long text) to pre-warm CUDA kernels

---

## v1.0.0 — Initial Release (2026-03-24)

- WebSocket server wrapping ai4bharat/indic-parler-tts
- 22 Indian languages + 3 English variants, 69 voice combinations
- Real-time WebSocket API + async batch REST API on same port
- In-memory LRU audio cache for repeated phrases
- Optional API key authentication
- Voice style control (default, warm, formal) with custom description override
- 8kHz output support for Asterisk/telephony
- Apple Silicon (MPS) support with conv1d workaround
- Docker + Google Cloud Run deployment
- Browser test clients (test.html, test-batch.html)
