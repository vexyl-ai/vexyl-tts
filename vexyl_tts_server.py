"""
vexyl_tts_server.py
VEXYL-TTS Server
------------------------------------------------------
Wraps ai4bharat/indic-parler-tts in a WebSocket server.
Accepts JSON text requests, returns base64-encoded WAV audio.
Also exposes a batch synthesis API (POST /batch/synthesize).

Usage:
    pip install git+https://github.com/huggingface/parler-tts.git
    pip install transformers torch soundfile websockets numpy
    python vexyl_tts_server.py

Optional env vars:
    PORT                      (default: 8080, Cloud Run injects this)
    VEXYL_TTS_HOST            (default: 0.0.0.0)
    VEXYL_TTS_PORT            (fallback if PORT unset)
    VEXYL_TTS_DEVICE          (default: auto)  options: auto, cpu, cuda, mps
    VEXYL_TTS_CACHE_SIZE      (default: 200)   LRU cache capacity
    VEXYL_TTS_API_KEY         (default: empty)  shared secret; if set, clients must send X-API-Key header
    VEXYL_TTS_MAX_CONN        (default: 50)     max concurrent WebSocket connections
"""

import asyncio
import websockets
from websockets.asyncio.server import ServerConnection
import json
import base64
import hashlib
import numpy as np
import torch
import soundfile as sf
import os
import io
import logging
import time
import signal
import threading
import hmac
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from http import HTTPStatus
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [VexylTTS] %(levelname)s %(message)s"
)
log = logging.getLogger("vexyl_tts")

# ─── Config ────────────────────────────────────────────────────────────────────
HOST            = os.getenv("VEXYL_TTS_HOST",   "0.0.0.0")
PORT            = int(os.getenv("PORT", os.getenv("VEXYL_TTS_PORT", "8080")))
DEVICE_PREF     = os.getenv("VEXYL_TTS_DEVICE", "auto")
CACHE_SIZE      = int(os.getenv("VEXYL_TTS_CACHE_SIZE", "200"))
API_KEY         = os.getenv("VEXYL_TTS_API_KEY", "")
MAX_CONNECTIONS = int(os.getenv("VEXYL_TTS_MAX_CONN", "50"))
OUTPUT_SAMPLE_RATE = int(os.getenv("VEXYL_TTS_SAMPLE_RATE", "0"))  # 0 = native (44100), set 8000 for Asterisk

# Batch synthesis config
BATCH_MAX_TEXT_LENGTH = 5000          # max characters per request
BATCH_MAX_JOBS       = 1000
BATCH_JOB_TTL        = 3600          # 1 hour
BATCH_MAX_BODY_SIZE  = 64 * 1024     # 64KB max POST body

# ─── Voice presets per language ────────────────────────────────────────────────
# Tuned for healthcare IVR: calm, clear, professional.
VOICE_PRESETS = {
    "ml-IN": {
        "default": "Anjali speaks in a calm, clear, and professional tone with a moderate speed and low pitch. The recording is of very high quality with no background noise.",
        "warm":    "Anjali speaks in a warm and empathetic tone, slightly slow-paced for clarity. The recording is of very high quality with no background noise.",
        "formal":  "Harish speaks in a formal, neutral tone with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    },
    "hi-IN": {
        "default": "Divya speaks in a calm, clear, and professional tone with a moderate speed and neutral pitch. The recording is of very high quality with no background noise.",
        "warm":    "Divya speaks in a warm and friendly tone, slightly slow-paced. The recording is of very high quality with no background noise.",
        "formal":  "Rohit speaks in a formal, neutral tone with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    },
    "ta-IN": {
        "default": "Kavitha speaks in a calm, clear, and professional tone with a moderate speed. The recording is of very high quality with no background noise.",
        "warm":    "Kavitha speaks in a warm and empathetic tone, slightly slow-paced for clarity. The recording is of very high quality with no background noise.",
        "formal":  "Jaya speaks in a formal, neutral tone with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    },
    "te-IN": {
        "default": "Lalitha speaks in a calm, clear, and professional tone with a moderate speed. The recording is of very high quality with no background noise.",
        "warm":    "Lalitha speaks in a warm and empathetic tone, slightly slow-paced for clarity. The recording is of very high quality with no background noise.",
        "formal":  "Prakash speaks in a formal, neutral tone with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    },
    "kn-IN": {
        "default": "Anu speaks in a calm, clear, and professional tone with a moderate speed. The recording is of very high quality with no background noise.",
        "warm":    "Anu speaks in a warm and empathetic tone, slightly slow-paced for clarity. The recording is of very high quality with no background noise.",
        "formal":  "Suresh speaks in a formal, neutral tone with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    },
    "bn-IN": {
        "default": "Aditi speaks in a calm, clear, and professional tone with a moderate speed. The recording is of very high quality with no background noise.",
        "warm":    "Aditi speaks in a warm and empathetic tone, slightly slow-paced for clarity. The recording is of very high quality with no background noise.",
        "formal":  "Arjun speaks in a formal, neutral tone with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    },
    "gu-IN": {
        "default": "Neha speaks in a calm, clear, and professional tone with a moderate speed. The recording is of very high quality with no background noise.",
        "warm":    "Neha speaks in a warm and empathetic tone, slightly slow-paced for clarity. The recording is of very high quality with no background noise.",
        "formal":  "Yash speaks in a formal, neutral tone with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    },
    "mr-IN": {
        "default": "Sunita speaks in a calm, clear, and professional tone with a moderate speed. The recording is of very high quality with no background noise.",
        "warm":    "Sunita speaks in a warm and empathetic tone, slightly slow-paced for clarity. The recording is of very high quality with no background noise.",
        "formal":  "Sanjay speaks in a formal, neutral tone with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    },
    "en-IN": {
        "default": "Mary speaks in a calm, clear, and professional tone with a moderate speed. The recording is of very high quality with no background noise.",
        "warm":    "Mary speaks in a warm and empathetic tone, slightly slow-paced for clarity. The recording is of very high quality with no background noise.",
        "formal":  "Thoma speaks in a formal, neutral tone with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    },
    "pa-IN": {
        "default": "Divjot speaks in a calm, clear, and professional tone with a moderate speed. The recording is of very high quality with no background noise.",
        "warm":    "Divjot speaks in a warm and empathetic tone, slightly slow-paced for clarity. The recording is of very high quality with no background noise.",
        "formal":  "Gurpreet speaks in a formal, neutral tone with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    },
    "or-IN": {
        "default": "Debjani speaks in a calm, clear, and professional tone with a moderate speed. The recording is of very high quality with no background noise.",
        "warm":    "Debjani speaks in a warm and empathetic tone, slightly slow-paced for clarity. The recording is of very high quality with no background noise.",
        "formal":  "Manas speaks in a formal, neutral tone with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    },
    "as-IN": {
        "default": "Sita speaks in a calm, clear, and professional tone with a moderate speed. The recording is of very high quality with no background noise.",
        "warm":    "Sita speaks in a warm and empathetic tone, slightly slow-paced for clarity. The recording is of very high quality with no background noise.",
        "formal":  "Amit speaks in a formal, neutral tone with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    },
    "ur-IN": {
        "default": "Zainab speaks in a calm, clear, and professional tone with a moderate speed. The recording is of very high quality with no background noise.",
        "warm":    "Zainab speaks in a warm and empathetic tone, slightly slow-paced for clarity. The recording is of very high quality with no background noise.",
        "formal":  "Rohit speaks in a formal, neutral tone with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    },
    "ne-IN": {
        "default": "Amrita speaks in a calm, clear, and professional tone with a moderate speed. The recording is of very high quality with no background noise.",
        "warm":    "Amrita speaks in a warm and empathetic tone, slightly slow-paced for clarity. The recording is of very high quality with no background noise.",
        "formal":  "Ram speaks in a formal, neutral tone with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    },
    "sa-IN": {
        "default": "Vasudha speaks in a calm, clear, and professional tone with a moderate speed. The recording is of very high quality with no background noise.",
        "warm":    "Vasudha speaks in a warm and empathetic tone, slightly slow-paced for clarity. The recording is of very high quality with no background noise.",
        "formal":  "Aryan speaks in a formal, neutral tone with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    },
    "brx-IN": {
        "default": "Bimala speaks in a calm, clear, and professional tone with a moderate speed. The recording is of very high quality with no background noise.",
        "warm":    "Bimala speaks in a warm and empathetic tone, slightly slow-paced for clarity. The recording is of very high quality with no background noise.",
        "formal":  "Bikram speaks in a formal, neutral tone with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    },
    "doi-IN": {
        "default": "Meena speaks in a calm, clear, and professional tone with a moderate speed. The recording is of very high quality with no background noise.",
        "warm":    "Meena speaks in a warm and empathetic tone, slightly slow-paced for clarity. The recording is of very high quality with no background noise.",
        "formal":  "Vikram speaks in a formal, neutral tone with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    },
    "kok-IN": {
        "default": "Priya speaks in a calm, clear, and professional tone with a moderate speed. The recording is of very high quality with no background noise.",
        "warm":    "Priya speaks in a warm and empathetic tone, slightly slow-paced for clarity. The recording is of very high quality with no background noise.",
        "formal":  "Kaustubh speaks in a formal, neutral tone with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    },
    "mai-IN": {
        "default": "Shruti speaks in a calm, clear, and professional tone with a moderate speed. The recording is of very high quality with no background noise.",
        "warm":    "Shruti speaks in a warm and empathetic tone, slightly slow-paced for clarity. The recording is of very high quality with no background noise.",
        "formal":  "Saurabh speaks in a formal, neutral tone with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    },
    "mni-IN": {
        "default": "Leima speaks in a calm, clear, and professional tone with a moderate speed. The recording is of very high quality with no background noise.",
        "warm":    "Leima speaks in a warm and empathetic tone, slightly slow-paced for clarity. The recording is of very high quality with no background noise.",
        "formal":  "Tomba speaks in a formal, neutral tone with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    },
    "sat-IN": {
        "default": "Sumitra speaks in a calm, clear, and professional tone with a moderate speed. The recording is of very high quality with no background noise.",
        "warm":    "Sumitra speaks in a warm and empathetic tone, slightly slow-paced for clarity. The recording is of very high quality with no background noise.",
        "formal":  "Raju speaks in a formal, neutral tone with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    },
    "sd-IN": {
        "default": "Hema speaks in a calm, clear, and professional tone with a moderate speed. The recording is of very high quality with no background noise.",
        "warm":    "Hema speaks in a warm and empathetic tone, slightly slow-paced for clarity. The recording is of very high quality with no background noise.",
        "formal":  "Mohan speaks in a formal, neutral tone with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    },
    "_default": {
        "default": "A female speaker delivers calm, clear, and professional speech with moderate speed. The recording is of very high quality with no background noise.",
        "warm":    "A female speaker delivers warm and empathetic speech, slightly slow-paced for clarity. The recording is of very high quality with no background noise.",
        "formal":  "A male speaker delivers formal, neutral speech with precise diction and moderate speed. The recording is of very high quality with no background noise.",
    }
}

# VEXYL language codes -> Parler-TTS language names
LANG_MAP = {
    "ml-IN": "malayalam", "hi-IN": "hindi",      "ta-IN": "tamil",
    "te-IN": "telugu",    "kn-IN": "kannada",    "bn-IN": "bengali",
    "gu-IN": "gujarati",  "mr-IN": "marathi",    "pa-IN": "punjabi",
    "or-IN": "odia",      "as-IN": "assamese",   "ur-IN": "urdu",
    "ne-IN": "nepali",    "sa-IN": "sanskrit",   "en-IN": "english",
    "brx-IN": "bodo",     "doi-IN": "dogri",     "kok-IN": "konkani",
    "mai-IN": "maithili", "mni-IN": "manipuri",  "sat-IN": "santali",
    "sd-IN": "sindhi",    "en-US": "english",    "en-GB": "english",
}

# ─── Connection Limits ────────────────────────────────────────────────────────
_conn_semaphore: asyncio.Semaphore   # initialized in main()
active_connections: int = 0
_server_start_time: float = 0.0

# ─── Model globals ─────────────────────────────────────────────────────────────
model          = None
tokenizer      = None
desc_tokenizer = None
device         = None
_infer_lock    = threading.Lock()

# ─── LRU Cache ────────────────────────────────────────────────────────────────
class LRUCache:
    def __init__(self, capacity):
        self.cache    = OrderedDict()
        self.capacity = capacity

    def get(self, key):
        if key not in self.cache:
            return None
        self.cache.move_to_end(key)
        return self.cache[key]

    def put(self, key, value):
        self.cache[key] = value
        self.cache.move_to_end(key)
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)

    def __len__(self):
        return len(self.cache)

audio_cache = LRUCache(CACHE_SIZE)
cache_hits  = 0
cache_total = 0

# ─── Batch Job Types ─────────────────────────────────────────────────────────

class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class BatchJob:
    job_id: str
    status: JobStatus
    text: str
    language: str
    style: str
    created_at: float
    description: Optional[str] = None
    audio_b64: Optional[str] = None
    sample_rate: Optional[int] = None
    latency_ms: Optional[int] = None
    completed_at: Optional[float] = None
    error_message: Optional[str] = None

_batch_jobs: dict[str, BatchJob] = {}
_batch_queue: asyncio.Queue = None       # initialized in main()
_batch_worker_task: asyncio.Task = None
_batch_cleanup_task: asyncio.Task = None

# ─── Model Loader ──────────────────────────────────────────────────────────────
def load_model():
    global model, tokenizer, desc_tokenizer, device

    if DEVICE_PREF == "auto":
        if torch.cuda.is_available():
            device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"
    else:
        device = DEVICE_PREF

    log.info(f"Loading ai4bharat/indic-parler-tts on {device}...")
    start = time.time()

    from parler_tts import ParlerTTSForConditionalGeneration
    from transformers import AutoTokenizer

    model = ParlerTTSForConditionalGeneration.from_pretrained(
        "ai4bharat/indic-parler-tts"
    ).to(device)
    model.eval()

    # MPS workaround: DAC audio decoder uses conv1d with >65536 output channels
    # which MPS doesn't support. Move the audio encoder to CPU and wrap its
    # decode method to automatically transfer tensors from MPS → CPU.
    if device == "mps":
        model.audio_encoder = model.audio_encoder.to("cpu")
        _original_decode = model.audio_encoder.decode
        def _cpu_decode(*args, **kwargs):
            args = tuple(a.to("cpu") if isinstance(a, torch.Tensor) else a for a in args)
            kwargs = {k: v.to("cpu") if isinstance(v, torch.Tensor) else v for k, v in kwargs.items()}
            return _original_decode(*args, **kwargs)
        model.audio_encoder.decode = _cpu_decode
        log.info("Moved audio_encoder to CPU (MPS conv1d channel limit workaround)")

    tokenizer      = AutoTokenizer.from_pretrained("ai4bharat/indic-parler-tts")
    desc_tokenizer = AutoTokenizer.from_pretrained(
        model.config.text_encoder._name_or_path
    )

    elapsed = time.time() - start
    log.info(f"Model loaded in {elapsed:.1f}s | device={device} | sample_rate={model.config.sampling_rate}Hz")


# ─── TTS Core ─────────────────────────────────────────────────────────────────
def get_voice_description(lang_code, style="default"):
    presets = VOICE_PRESETS.get(lang_code, VOICE_PRESETS["_default"])
    return presets.get(style, presets.get("default"))


def _synthesize_sync(text, lang_code, style="default", custom_description=None):
    """Run inference. Returns (WAV bytes, sample_rate)."""
    description = custom_description or get_voice_description(lang_code, style)

    desc_inputs   = desc_tokenizer(description, return_tensors="pt").to(device)
    prompt_inputs = tokenizer(text, return_tensors="pt").to(device)

    with _infer_lock:
        with torch.no_grad():
            generation = model.generate(
                input_ids=desc_inputs.input_ids,
                attention_mask=desc_inputs.attention_mask,
                prompt_input_ids=prompt_inputs.input_ids,
                prompt_attention_mask=prompt_inputs.attention_mask,
            )

    audio_arr = generation.cpu().numpy().squeeze().astype(np.float32)

    # Normalize
    peak = np.abs(audio_arr).max()
    if peak > 1.0:
        audio_arr = audio_arr / peak

    native_rate = model.config.sampling_rate
    sample_rate = native_rate

    # Downsample if output sample rate is configured (e.g. 8000 for Asterisk)
    if OUTPUT_SAMPLE_RATE and OUTPUT_SAMPLE_RATE != native_rate:
        num_samples = int(len(audio_arr) * OUTPUT_SAMPLE_RATE / native_rate)
        audio_arr = np.interp(
            np.linspace(0, len(audio_arr) - 1, num_samples),
            np.arange(len(audio_arr)),
            audio_arr,
        ).astype(np.float32)
        sample_rate = OUTPUT_SAMPLE_RATE

    buf = io.BytesIO()
    sf.write(buf, audio_arr, sample_rate, format="WAV", subtype="PCM_16")
    buf.seek(0)
    return buf.read(), sample_rate


async def synthesize(text, lang_code, style="default", custom_description=None):
    """Async wrapper for synthesis."""
    return await asyncio.to_thread(_synthesize_sync, text, lang_code, style, custom_description)


def make_cache_key(text, lang_code, style):
    raw = f"{text}|{lang_code}|{style}|indic-parler-tts"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ─── Batch Worker ──────────────────────────────────────────────────────────────

async def _batch_worker():
    """Background coroutine — pulls jobs from queue and runs synthesis."""
    log.info("Batch worker started")
    while True:
        try:
            job_id = await _batch_queue.get()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.error("[batch] Error getting from queue", exc_info=True)
            await asyncio.sleep(1)
            continue

        try:
            job = _batch_jobs.get(job_id)
            if not job or job.status != JobStatus.QUEUED:
                continue

            job.status = JobStatus.PROCESSING
            log.info(f"[batch] Processing job {job_id} ({job.language}/{job.style}, {len(job.text)} chars)")

            start = time.time()
            wav_bytes, sample_rate = await synthesize(job.text, job.language, job.style, job.description)
            latency = int((time.time() - start) * 1000)

            job.audio_b64 = base64.b64encode(wav_bytes).decode()
            job.sample_rate = sample_rate
            job.latency_ms = latency
            job.status = JobStatus.COMPLETED
            job.completed_at = time.time()

            log.info(f"[batch] Job {job_id} completed ({latency}ms)")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error(f"[batch] Job {job_id} failed: {e}", exc_info=True)
            if job_id in _batch_jobs:
                _batch_jobs[job_id].status = JobStatus.FAILED
                _batch_jobs[job_id].error_message = "Synthesis failed"
                _batch_jobs[job_id].completed_at = time.time()
        finally:
            try:
                _batch_queue.task_done()
            except ValueError:
                pass


async def _batch_cleanup_loop():
    """Remove completed/failed jobs older than BATCH_JOB_TTL every 5 minutes."""
    while True:
        await asyncio.sleep(300)
        now = time.time()
        expired = [
            jid for jid, job in _batch_jobs.items()
            if job.completed_at and (now - job.completed_at) > BATCH_JOB_TTL
        ]
        for jid in expired:
            del _batch_jobs[jid]
        if expired:
            log.info(f"[batch] Cleaned up {len(expired)} expired jobs")


# ─── WebSocket Handler ─────────────────────────────────────────────────────────
async def handle_connection(websocket):
    """
    Protocol (all JSON):
    Client → {"type":"synthesize","text":"...","lang":"ml-IN","style":"default","request_id":"x"}
    Server ← {"type":"audio","request_id":"x","audio_b64":"...","sample_rate":22050,"cached":bool,"latency_ms":N}

    Client → {"type":"get_stats"}
    Server ← {"type":"stats","cache_hits":N,"cache_total":N,"hit_rate":N}

    On connect:
    Server ← {"type":"ready","model":"indic-parler-tts","sample_rate":22050}
    """
    global cache_hits, cache_total, active_connections
    remote = websocket.remote_address
    active_connections += 1

    try:
        await websocket.send(json.dumps({
            "type":        "ready",
            "model":       "indic-parler-tts",
            "sample_rate": model.config.sampling_rate,
            "languages":   list(LANG_MAP.keys()),
        }))
        log.info(f"New connection: {remote}")

        async for message in websocket:
            try:
                msg = json.loads(message)
            except json.JSONDecodeError:
                await websocket.send(json.dumps({"type": "error", "message": "Invalid JSON"}))
                continue

            msg_type   = msg.get("type")
            request_id = msg.get("request_id", f"req_{int(time.time())}")

            if msg_type == "synthesize":
                text        = msg.get("text", "").strip()
                lang_code   = msg.get("lang", "ml-IN")
                style       = msg.get("style", "default")
                custom_desc = msg.get("description")

                if not text:
                    await websocket.send(json.dumps({
                        "type": "error", "request_id": request_id,
                        "message": "Empty text"
                    }))
                    continue

                cache_total += 1
                ck = make_cache_key(text, lang_code, style)
                cached = audio_cache.get(ck)

                if cached:
                    cache_hits += 1
                    log.info(f"[{request_id}] CACHE HIT ({cache_hits/cache_total*100:.0f}%) | '{text[:40]}'")
                    await websocket.send(json.dumps({
                        "type": "audio", "request_id": request_id,
                        "audio_b64": cached["b64"],
                        "sample_rate": cached["sr"],
                        "cached": True, "latency_ms": 2
                    }))
                else:
                    start = time.time()
                    try:
                        wav_bytes, sample_rate = await synthesize(text, lang_code, style, custom_desc)
                        latency   = int((time.time() - start) * 1000)
                        b64audio  = base64.b64encode(wav_bytes).decode()
                        audio_cache.put(ck, {"b64": b64audio, "sr": sample_rate})

                        log.info(f"[{request_id}] Synthesized {latency}ms | {lang_code}/{style} | '{text[:40]}'")
                        await websocket.send(json.dumps({
                            "type": "audio", "request_id": request_id,
                            "audio_b64": b64audio,
                            "sample_rate": sample_rate,
                            "cached": False, "latency_ms": latency
                        }))
                    except Exception as e:
                        log.error(f"[{request_id}] Synthesis failed: {e}", exc_info=True)
                        await websocket.send(json.dumps({
                            "type": "error", "request_id": request_id, "message": str(e)
                        }))

            elif msg_type == "get_stats":
                await websocket.send(json.dumps({
                    "type": "stats",
                    "cache_size":  len(audio_cache),
                    "cache_hits":  cache_hits,
                    "cache_total": cache_total,
                    "hit_rate":    round(cache_hits / max(cache_total, 1) * 100, 1),
                    "device":      device,
                }))

            elif msg_type == "ping":
                await websocket.send(json.dumps({"type": "pong"}))

    except websockets.exceptions.ConnectionClosed:
        log.info(f"Disconnected: {remote}")
    except Exception as e:
        log.error(f"Handler error: {e}", exc_info=True)
        try:
            await websocket.send(json.dumps({"type": "error", "message": "Internal server error"}))
        except Exception:
            pass
    finally:
        active_connections -= 1


async def _limited_handler(websocket):
    """Wrap handle_connection with a semaphore to cap concurrent connections."""
    if _conn_semaphore.locked() and _conn_semaphore._value == 0:
        await websocket.close(1013, "Server at capacity")
        log.warning(f"Rejected connection from {websocket.remote_address} — at capacity ({MAX_CONNECTIONS})")
        return
    async with _conn_semaphore:
        await handle_connection(websocket)


# ─── Batch-Capable Connection ────────────────────────────────────────────────
# websockets 16.x rejects POST requests at the HTTP/1.1 parsing level before
# _process_request() is ever called.  We subclass ServerConnection and override
# data_received() to intercept POST requests at the transport level.

class BatchCapableConnection(ServerConnection):
    """ServerConnection subclass that intercepts HTTP POST for batch endpoints."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._post_buffer = b""
        self._is_post: Optional[bool] = None  # None = undetermined
        self._handled_as_http = False

    async def handshake(self, *args, **kwargs):
        """Override to suppress the EOF error when we already handled as HTTP.
        The race: handshake() starts awaiting protocol data, then data_received()
        intercepts POST/OPTIONS and closes the transport, causing an EOF here."""
        try:
            return await super().handshake(*args, **kwargs)
        except Exception:
            if self._handled_as_http:
                return  # suppress — we already sent an HTTP response
            raise

    def data_received(self, data: bytes) -> None:
        # First chunk: determine request type
        if self._is_post is None:
            self._post_buffer = data
            if data[:7] == b"OPTIONS":
                self._handled_as_http = True
                self._send_cors_preflight()
                return
            elif data[:4] == b"POST":
                self._is_post = True
                self._handled_as_http = True
                self._try_handle_post()
                return
            else:
                self._is_post = False
                super().data_received(data)
                return

        if self._is_post:
            # Cap buffer to prevent unbounded memory growth
            max_buffer = BATCH_MAX_BODY_SIZE + 64 * 1024
            if len(self._post_buffer) + len(data) > max_buffer:
                self._send_json_response(413, "Payload Too Large",
                                         {"error": "Request too large"})
                return
            self._post_buffer += data
            self._try_handle_post()
        else:
            super().data_received(data)

    def _try_handle_post(self):
        """Check if we have the full POST request, then handle it."""
        header_end = self._post_buffer.find(b"\r\n\r\n")
        if header_end == -1:
            return  # need more header data

        headers_section = self._post_buffer[:header_end]
        body_start = header_end + 4

        # Parse Content-Length (with validation)
        content_length = 0
        for line in headers_section.decode("utf-8", errors="replace").split("\r\n"):
            if line.lower().startswith("content-length:"):
                try:
                    content_length = int(line.split(":", 1)[1].strip())
                except (ValueError, IndexError):
                    self._send_json_response(400, "Bad Request",
                                             {"error": "Invalid Content-Length"})
                    return
                if content_length < 0 or content_length > BATCH_MAX_BODY_SIZE:
                    self._send_json_response(413, "Payload Too Large",
                                             {"error": "Content-Length exceeds limit"})
                    return
                break

        body_so_far = self._post_buffer[body_start:]
        if len(body_so_far) < content_length:
            return  # need more body data

        # We have the full request
        body = body_so_far[:content_length]
        headers_raw = headers_section.decode("utf-8", errors="replace")
        task = asyncio.ensure_future(self._handle_post(headers_raw, body))
        task.add_done_callback(self._post_task_done)

    def _post_task_done(self, task: asyncio.Task):
        """Callback for POST handler task — log unhandled exceptions."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            log.error(f"[batch] Unhandled POST handler error: {exc}", exc_info=exc)

    async def _handle_post(self, headers_raw: str, body: bytes):
        """Route and handle the POST request."""
        try:
            lines = headers_raw.split("\r\n")
            request_line = lines[0]  # e.g. "POST /batch/synthesize HTTP/1.1"
            parts = request_line.split(" ", 2)
            path = parts[1] if len(parts) > 1 else "/"

            # Parse headers into dict
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    key, val = line.split(":", 1)
                    headers[key.strip().lower()] = val.strip()

            # API key check (timing-safe)
            if API_KEY:
                client_key = headers.get("x-api-key", "")
                if not hmac.compare_digest(client_key, API_KEY):
                    self._send_json_response(403, "Forbidden",
                                             {"error": "Invalid or missing API key"})
                    return

            if path == "/batch/synthesize":
                await self._handle_batch_synthesize(headers, body)
            else:
                self._send_json_response(404, "Not Found",
                                         {"error": f"Unknown endpoint: {path}"})
        except Exception as e:
            log.error(f"[batch] POST handler error: {e}", exc_info=True)
            self._send_json_response(500, "Internal Server Error",
                                     {"error": "Internal server error"})

    async def _handle_batch_synthesize(self, headers: dict, body: bytes):
        """Handle POST /batch/synthesize — accept JSON for async synthesis."""
        content_type = headers.get("content-type", "")

        if "application/json" not in content_type:
            self._send_json_response(400, "Bad Request",
                                     {"error": "Content-Type must be application/json"})
            return

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._send_json_response(400, "Bad Request",
                                     {"error": "Invalid JSON body"})
            return

        text = payload.get("text", "").strip()
        if not text:
            self._send_json_response(400, "Bad Request",
                                     {"error": "Missing 'text' field"})
            return

        if len(text) > BATCH_MAX_TEXT_LENGTH:
            self._send_json_response(400, "Bad Request",
                                     {"error": f"Text too long ({len(text)} chars). Max {BATCH_MAX_TEXT_LENGTH}"})
            return

        language = payload.get("lang", "ml-IN")
        style = payload.get("style", "default")
        description = payload.get("description")

        # Check job limit
        pending_count = sum(1 for j in _batch_jobs.values()
                           if j.status in (JobStatus.QUEUED, JobStatus.PROCESSING))
        if pending_count >= BATCH_MAX_JOBS:
            self._send_json_response(429, "Too Many Requests",
                                     {"error": f"Too many pending jobs (max {BATCH_MAX_JOBS})"})
            return

        # Create job
        job_id = f"batch_{uuid.uuid4().hex[:16]}"
        job = BatchJob(
            job_id=job_id,
            status=JobStatus.QUEUED,
            text=text,
            language=language,
            style=style,
            created_at=time.time(),
            description=description,
        )
        _batch_jobs[job_id] = job
        await _batch_queue.put(job_id)

        log.info(f"[batch] Job {job_id} queued: {language}/{style}, {len(text)} chars")

        self._send_json_response(201, "Created", {
            "job_id": job_id,
            "status": "queued",
            "language": language,
            "style": style,
            "text_length": len(text),
        })

    def _send_cors_preflight(self):
        """Respond to an OPTIONS preflight request."""
        response = (
            "HTTP/1.1 204 No Content\r\n"
            "Access-Control-Allow-Origin: *\r\n"
            "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
            "Access-Control-Allow-Headers: Content-Type, X-API-Key\r\n"
            "Access-Control-Max-Age: 86400\r\n"
            "Content-Length: 0\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("utf-8")
        try:
            self.transport.write(response)
            self.transport.close()
        except Exception:
            pass

    def _send_json_response(self, status_code: int, status_text: str, body_dict: dict):
        """Write a raw HTTP JSON response to the transport and close."""
        body = json.dumps(body_dict).encode("utf-8")
        response = (
            f"HTTP/1.1 {status_code} {status_text}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Access-Control-Allow-Origin: *\r\n"
            f"Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
            f"Access-Control-Allow-Headers: Content-Type, X-API-Key\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode("utf-8") + body
        try:
            self.transport.write(response)
            self.transport.close()
        except Exception:
            pass


# ─── CORS & HTTP Helpers ──────────────────────────────────────────────────────

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-API-Key",
}

def _json_response(connection, status: HTTPStatus, body_dict: dict):
    """Helper to build a JSON HTTP response via websockets' connection.respond()."""
    body = json.dumps(body_dict)
    response = connection.respond(status, body)
    response.headers["Content-Type"] = "application/json"
    for k, v in _CORS_HEADERS.items():
        response.headers[k] = v
    return response


def _process_request(connection, request):
    """Intercept HTTP requests before WebSocket upgrade.
    Serves /health, /batch/status/{id}, /batch/result/{id}.
    websockets 16.x API: (ServerConnection, Request) -> Response | None."""

    # ── Health check (no auth required) ──
    if request.path == "/health":
        queued = sum(1 for j in _batch_jobs.values() if j.status == JobStatus.QUEUED)
        return _json_response(connection, HTTPStatus.OK, {
            "status":             "ok",
            "model":              "indic-parler-tts",
            "device":             device,
            "cache_size":         len(audio_cache),
            "cache_capacity":     CACHE_SIZE,
            "cache_hit_rate":     round(cache_hits / max(cache_total, 1) * 100, 1),
            "active_connections": active_connections,
            "max_connections":    MAX_CONNECTIONS,
            "uptime_seconds":     round(time.time() - _server_start_time, 1),
            "batch_jobs_queued":  queued,
            "batch_jobs_total":   len(_batch_jobs),
        })

    # API key check — skip if no key configured
    if API_KEY:
        client_key = request.headers.get("X-API-Key", "")
        if not hmac.compare_digest(client_key, API_KEY):
            log.warning(f"Rejected connection — invalid or missing API key from {request.headers.get('Host', 'unknown')}")
            return connection.respond(HTTPStatus.FORBIDDEN, "Invalid or missing API key")

    # ── Batch status endpoint ──
    if request.path.startswith("/batch/status/"):
        job_id = request.path[len("/batch/status/"):]
        job = _batch_jobs.get(job_id)
        if not job:
            return _json_response(connection, HTTPStatus.NOT_FOUND,
                                  {"error": "Job not found", "job_id": job_id})

        result = {
            "job_id": job.job_id,
            "status": job.status.value,
            "language": job.language,
            "style": job.style,
            "text_length": len(job.text),
            "created_at": job.created_at,
        }
        if job.status == JobStatus.COMPLETED:
            result["audio_b64"] = job.audio_b64
            result["sample_rate"] = job.sample_rate
            result["latency_ms"] = job.latency_ms
            result["completed_at"] = job.completed_at
        elif job.status == JobStatus.FAILED:
            result["error_message"] = job.error_message
            result["completed_at"] = job.completed_at

        return _json_response(connection, HTTPStatus.OK, result)

    # ── Batch result endpoint ──
    if request.path.startswith("/batch/result/"):
        job_id = request.path[len("/batch/result/"):]
        job = _batch_jobs.get(job_id)
        if not job:
            return _json_response(connection, HTTPStatus.NOT_FOUND,
                                  {"error": "Job not found", "job_id": job_id})

        if job.status == JobStatus.COMPLETED:
            return _json_response(connection, HTTPStatus.OK, {
                "job_id": job.job_id,
                "status": "completed",
                "audio_b64": job.audio_b64,
                "sample_rate": job.sample_rate,
                "language": job.language,
                "style": job.style,
                "latency_ms": job.latency_ms,
            })
        elif job.status == JobStatus.FAILED:
            return _json_response(connection, HTTPStatus.OK, {
                "job_id": job.job_id,
                "status": "failed",
                "error_message": job.error_message,
            })
        else:
            # Still processing — 202 Accepted
            return _json_response(connection, HTTPStatus.ACCEPTED, {
                "job_id": job.job_id,
                "status": job.status.value,
                "language": job.language,
                "style": job.style,
            })

    # ── Fix headers mangled by reverse proxies (e.g. Cloudflare Tunnel) ──
    if request.headers.get("Sec-WebSocket-Key"):
        conn_values = [v.lower() for v in request.headers.get_all("Connection")]
        if not any("upgrade" in v for v in conn_values):
            log.info(f"Fixing Connection header mangled by reverse proxy (was: {request.headers.get('Connection')})")
            del request.headers["Connection"]
            request.headers["Connection"] = "Upgrade"

        upgrade_values = [v.lower() for v in request.headers.get_all("Upgrade")]
        if not any("websocket" in v for v in upgrade_values):
            log.info(f"Fixing Upgrade header mangled by reverse proxy (was: {request.headers.get('Upgrade')})")
            if "Upgrade" in request.headers:
                del request.headers["Upgrade"]
            request.headers["Upgrade"] = "websocket"

    return None


# ─── Main ──────────────────────────────────────────────────────────────────────
async def main():
    global _conn_semaphore, _server_start_time, _batch_queue
    global _batch_worker_task, _batch_cleanup_task

    load_model()

    log.info("Running warm-up inference...")
    _synthesize_sync("Hello", "en-IN", "default")
    log.info("Warm-up complete")

    _conn_semaphore = asyncio.Semaphore(MAX_CONNECTIONS)
    _server_start_time = time.time()

    # Initialize batch processing
    _batch_queue = asyncio.Queue()
    _batch_worker_task = asyncio.create_task(_batch_worker())
    _batch_cleanup_task = asyncio.create_task(_batch_cleanup_loop())

    log.info(f"Starting VEXYL-TTS WebSocket server on ws://{HOST}:{PORT}")

    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: _handle_signal(s, stop_event))

    async with websockets.serve(
        _limited_handler,
        HOST,
        PORT,
        max_size=512 * 1024,         # 512KB max message (text requests are small)
        ping_interval=30,
        ping_timeout=10,
        close_timeout=5,
        process_request=_process_request,
        create_connection=BatchCapableConnection,
    ) as server:
        log.info(f"VEXYL-TTS server ready | ws://{HOST}:{PORT} | max_conn={MAX_CONNECTIONS} | batch=enabled")
        await stop_event.wait()

        log.info("Shutting down... cancelling batch tasks")
        _batch_worker_task.cancel()
        _batch_cleanup_task.cancel()
        try:
            await _batch_worker_task
        except asyncio.CancelledError:
            pass
        try:
            await _batch_cleanup_task
        except asyncio.CancelledError:
            pass

        log.info("Closing active connections")
        server.close()
        await server.wait_closed()
        log.info("Server stopped cleanly")


def _handle_signal(sig, stop_event: asyncio.Event):
    log.info(f"Received {signal.Signals(sig).name}, initiating shutdown...")
    stop_event.set()


if __name__ == "__main__":
    asyncio.run(main())
