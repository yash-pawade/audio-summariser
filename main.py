"""
Real-Time Microphone Summarizer
================================
• Records from microphone in rolling chunks (default 30 s)
• Transcribes each chunk via Groq Whisper as soon as it's ready
• Shows the live transcript and regenerates a rolling summary after every chunk
• No file input, no pydub/ffmpeg — pure sounddevice + soundfile (WAV)
• Designed to stay well within 512 MB RAM

Usage:
    python main.py                    # default 30-second chunks
    python main.py --chunk-sec 20     # shorter chunks (faster updates)
    python main.py --chunk-sec 60     # longer chunks (more context per call)
"""

import io
import os
import sys
import time
import wave
import math
import queue
import struct
import logging
import argparse
import tempfile
import threading
from datetime import datetime

import numpy as np
import sounddevice as sd
from dotenv import load_dotenv
from groq import Groq

# ── Bootstrap ─────────────────────────────────────────────────────────────────
load_dotenv()

logging.basicConfig(
    level=logging.WARNING,          # keep console clean
    format="%(asctime)s [%(levelname)s] %(message)s",
)
for noisy in ("httpx", "httpcore", "groq"):
    logging.getLogger(noisy).setLevel(logging.ERROR)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

# ── Constants ──────────────────────────────────────────────────────────────────
SAMPLE_RATE  = 16_000      # Hz — optimal for Whisper
CHANNELS     = 1           # mono
DTYPE        = "int16"     # 16-bit PCM — tiny footprint (~1.9 MB / 30 s)
MAX_RETRIES  = 3

# ── ANSI helpers ──────────────────────────────────────────────────────────────
_use_color = sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _use_color else text

def hr(char="─", width=60) -> str:
    return char * width

def print_header():
    os.system("cls" if os.name == "nt" else "clear")
    print(_c("1;36", "╔" + "═" * 58 + "╗"))
    print(_c("1;36", "║") + _c("1;97", "   🎙  REAL-TIME MIC SUMMARIZER  (Groq Whisper + Llama)  ") + _c("1;36", "║"))
    print(_c("1;36", "╚" + "═" * 58 + "╝"))
    print()

def section(title: str):
    print("\n" + _c("33", hr("─")) )
    print(_c("1;33", f"  {title}"))
    print(_c("33", hr("─")))

# ── WAV helper — write int16 PCM to a bytes buffer ───────────────────────────

def frames_to_wav_bytes(frames: list[np.ndarray]) -> bytes:
    """Concatenate int16 numpy frames and return a valid WAV byte string."""
    audio = np.concatenate(frames, axis=0).flatten()      # (N,) int16
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)          # int16 = 2 bytes
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())
    return buf.getvalue()

# ── Groq STT ──────────────────────────────────────────────────────────────────

def transcribe(client: Groq, wav_bytes: bytes, attempt: int = 0) -> str:
    """Send WAV bytes to Groq Whisper; return transcript string."""
    try:
        rsp = client.audio.transcriptions.create(
            file=("chunk.wav", wav_bytes, "audio/wav"),
            model="whisper-large-v3-turbo",
            response_format="text",
            language="en",
        )
        return rsp.strip() if isinstance(rsp, str) else str(rsp).strip()
    except Exception as exc:
        if attempt < MAX_RETRIES:
            wait = 2 ** attempt * 2
            print(_c("31", f"\n  ⚠  STT retry {attempt+1}/{MAX_RETRIES} in {wait}s — {exc}"))
            time.sleep(wait)
            return transcribe(client, wav_bytes, attempt + 1)
        print(_c("31", f"\n  ✗  STT failed: {exc}"))
        return ""

# ── Groq Summarization ────────────────────────────────────────────────────────

def summarize(client: Groq, transcript: str) -> str:
    """Produce a rolling bullet-point summary of the full transcript so far."""
    if not transcript.strip():
        return "(nothing to summarise yet)"
    try:
        rsp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a concise summarisation assistant. "
                        "Given an audio transcript, produce a clear, structured summary. "
                        "Use bullet points. Highlight key topics, decisions, and action items. "
                        "Be brief — max 200 words."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Summarise this transcript:\n\n{transcript}",
                },
            ],
            temperature=0.3,
            max_tokens=400,
        )
        return rsp.choices[0].message.content.strip()
    except Exception as exc:
        return f"(summary error: {exc})"

# ── Spinner ───────────────────────────────────────────────────────────────────

class Spinner:
    _FRAMES = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]

    def __init__(self, label: str = "Working"):
        self._label   = label
        self._stop    = threading.Event()
        self._thread  = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        i = 0
        while not self._stop.is_set():
            sys.stdout.write(f"\r  {self._FRAMES[i % len(self._FRAMES)]}  {self._label}…")
            sys.stdout.flush()
            i += 1
            time.sleep(0.08)
        sys.stdout.write("\r" + " " * (len(self._label) + 12) + "\r")
        sys.stdout.flush()

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        self._thread.join()

# ── Recording thread ──────────────────────────────────────────────────────────

class MicRecorder:
    """
    Continuously records from the default microphone into a queue of chunks.
    Each chunk is ~chunk_sec seconds of int16 PCM frames.
    """

    def __init__(self, chunk_sec: int = 30):
        self.chunk_sec   = chunk_sec
        self.chunk_size  = SAMPLE_RATE * chunk_sec  # samples per chunk
        self._q: queue.Queue[list[np.ndarray]] = queue.Queue()
        self._stop       = threading.Event()
        self._cur_frames: list[np.ndarray] = []
        self._cur_count  = 0

    def _callback(self, indata: np.ndarray, frames: int, t, status):
        if self._stop.is_set():
            return
        chunk = indata.copy().astype(np.int16)   # float32 → int16
        self._cur_frames.append(chunk)
        self._cur_count += frames
        if self._cur_count >= self.chunk_size:
            self._q.put(self._cur_frames)
            self._cur_frames = []
            self._cur_count  = 0

    def start(self):
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",          # sounddevice prefers float32 input
            callback=self._callback,
            blocksize=4096,           # ~256 ms latency
        )
        self._stream.start()

    def stop(self) -> list[np.ndarray] | None:
        """Signal stop; returns any remaining frames not yet queued."""
        self._stop.set()
        self._stream.stop()
        self._stream.close()
        return self._cur_frames if self._cur_frames else None

    def get_next_chunk(self, timeout: float = 0.2) -> list[np.ndarray] | None:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

# ── Main loop ─────────────────────────────────────────────────────────────────

def run(chunk_sec: int = 30):
    if not GROQ_API_KEY:
        print(_c("31", "  ✗  GROQ_API_KEY not found in .env — aborting."))
        sys.exit(1)

    client   = Groq(api_key=GROQ_API_KEY)
    recorder = MicRecorder(chunk_sec=chunk_sec)

    print_header()
    print(f"  Chunk interval : {_c('1', str(chunk_sec))} seconds")
    print(f"  Sample rate    : {SAMPLE_RATE} Hz  |  16-bit mono")
    print(f"  API model      : whisper-large-v3-turbo  +  llama-3.1-8b-instant")
    print()
    print(_c("90", "  Press  ENTER  to start recording."))
    print(_c("90", "  Press  ENTER  again at any time to stop.\n"))
    input()

    print(_c("1;32", "  🔴  Recording…  (press ENTER to stop)\n"))
    recorder.start()

    stop_flag   = threading.Event()
    full_transcript: list[str] = []
    chunk_num   = 0

    def wait_for_enter():
        input()
        stop_flag.set()

    listener = threading.Thread(target=wait_for_enter, daemon=True)
    listener.start()

    while not stop_flag.is_set():
        chunk_frames = recorder.get_next_chunk(timeout=0.3)
        if chunk_frames is None:
            continue

        chunk_num += 1
        ts = datetime.now().strftime("%H:%M:%S")
        section(f"Chunk #{chunk_num}  —  {ts}")

        # ── Transcribe ────────────────────────────────────────────────────────
        with Spinner("Transcribing"):
            wav_bytes = frames_to_wav_bytes(chunk_frames)
            text      = transcribe(client, wav_bytes)
            del wav_bytes          # free immediately

        if text:
            full_transcript.append(text)
            print(_c("1;97", "\n  📝 Transcript segment:"))
            print(f"  {_c('97', text)}\n")
        else:
            print(_c("90", "  (no speech detected in this chunk)\n"))

        # ── Rolling summary ───────────────────────────────────────────────────
        if full_transcript:
            with Spinner("Summarising"):
                combined = " ".join(full_transcript)
                summary  = summarize(client, combined)

            section("📋 Summary so far")
            for line in summary.splitlines():
                print(f"  {_c('96', line)}")
            print()

    # ── Handle remaining audio after ENTER pressed ────────────────────────────
    leftover = recorder.stop()

    if leftover:
        chunk_num += 1
        ts = datetime.now().strftime("%H:%M:%S")
        section(f"Chunk #{chunk_num}  —  {ts}  (final)")
        with Spinner("Transcribing final segment"):
            wav_bytes = frames_to_wav_bytes(leftover)
            text      = transcribe(client, wav_bytes)
            del wav_bytes

        if text:
            full_transcript.append(text)
            print(_c("1;97", "\n  📝 Transcript segment:"))
            print(f"  {_c('97', text)}\n")

    # ── Final summary ─────────────────────────────────────────────────────────
    if full_transcript:
        with Spinner("Generating final summary"):
            combined      = " ".join(full_transcript)
            final_summary = summarize(client, combined)

        print("\n" + _c("1;36", "╔" + "═" * 58 + "╗"))
        print(_c("1;36", "║") + _c("1;97", "   ✅  FINAL SUMMARY" + " " * 39) + _c("1;36", "║"))
        print(_c("1;36", "╚" + "═" * 58 + "╝"))
        for line in final_summary.splitlines():
            print(f"  {_c('1;96', line)}")
        print()

        print(_c("1;36", "╔" + "═" * 58 + "╗"))
        print(_c("1;36", "║") + _c("1;97", "   📜  FULL TRANSCRIPT" + " " * 37) + _c("1;36", "║"))
        print(_c("1;36", "╚" + "═" * 58 + "╝"))
        for line in combined.split(". "):
            if line.strip():
                print(f"  {line.strip()}.")
        print()
    else:
        print(_c("33", "\n  No speech was captured.\n"))

    print(_c("90", "  Session ended.\n"))

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Real-time microphone transcription & summarisation (Groq-powered)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--chunk-sec",
        type=int,
        default=30,
        metavar="N",
        help="Seconds of audio per transcription chunk (default: 30)",
    )
    args = parser.parse_args()

    if args.chunk_sec < 5 or args.chunk_sec > 120:
        parser.error("--chunk-sec must be between 5 and 120")

    run(chunk_sec=args.chunk_sec)
