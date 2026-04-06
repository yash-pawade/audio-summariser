# 🛠 Error Troubleshooting Guide

All possible errors in `main.py` with root causes and step-by-step fixes.

---

## 1. Setup & Environment

### ❌ `GROQ_API_KEY is not set`
- **Line:** 200–201
- **Cause:** `.env` file missing, empty, or key name is wrong
- **Fix:**
  1. Open `.env` in the `audio_summarizer/` folder
  2. Add: `GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxx`
  3. No spaces around `=`

---

### ❌ `ModuleNotFoundError: No module named 'groq'`
- **Line:** 22 (import block)
- **Cause:** Packages not installed or wrong Python being used
- **Fix:**
```powershell
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python main.py --mic
```

---

### ❌ `Python was not found` / `CouldNotAutoLoadModule`
- **Cause:** Windows Store Python stub running instead of venv Python
- **Fix:** Always run with the venv prefix:
```powershell
venv\Scripts\python main.py --mic
```

---

## 2. Microphone / Audio Capture

### ❌ `No audio captured. Is your microphone plugged in?`
- **Line:** 75
- **Cause:** Mic not connected, or Windows privacy blocking it
- **Fix:**
  1. **Windows Settings → Privacy → Microphone** → allow Desktop apps
  2. **Sound Settings → Input** → set mic as default, check it's not muted
  3. Test mic detection:
  ```powershell
  venv\Scripts\python -c "import sounddevice as sd; print(sd.query_devices())"
  ```

---

### ❌ `sounddevice.PortAudioError`
- **Line:** 61–66
- **Cause:** No audio input device found, or 16000 Hz not supported by mic
- **Fix:** Change sample rate in `main.py` line 35:
```python
SAMPLE_RATE = 44100
```

---

### ❌ `soundfile.LibsndfileError`
- **Line:** 82
- **Cause:** Recorded audio array is empty (mic permission issue)
- **Fix:** Resolve mic accessibility first (see above)

---

## 3. FFmpeg / Audio Loading

### ❌ `Could not load audio (...). Is ffmpeg installed?`
- **Line:** 146
- **Cause:** `ffmpeg.exe` missing from `venv\Scripts\`
- **Fix:** Re-download and copy ffmpeg:
```powershell
Invoke-WebRequest -Uri "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" -OutFile "ffmpeg.zip"
Expand-Archive -Path "ffmpeg.zip" -DestinationPath "."
Copy-Item "ffmpeg-master-latest-win64-gpl\bin\*.exe" -Destination "venv\Scripts\"
Remove-Item "ffmpeg.zip", "ffmpeg-master-latest-win64-gpl" -Recurse
```

---

### ❌ `FileNotFoundError: [WinError 2]`
- **Line:** 144
- **Cause:** File path given to `--audio` does not exist
- **Fix:** Use a full absolute path:
```powershell
venv\Scripts\python main.py --audio "C:\Users\you\Downloads\meeting.mp3"
```

---

### ❌ `pydub.exceptions.CouldntDecodeError`
- **Line:** 144
- **Cause:** Audio file is corrupted, DRM-protected, or unsupported format
- **Fix:** Convert to mp3 first:
```powershell
venv\Scripts\ffmpeg.exe -i input.m4a output.mp3
venv\Scripts\python main.py --audio output.mp3
```

---

## 4. Groq API — Transcription

### ❌ `STT retry X/4 — 401 Unauthorized`
- **Line:** 101
- **Cause:** API key is invalid or revoked
- **Fix:** Go to [console.groq.com](https://console.groq.com) → create new API key → update `.env`

---

### ❌ `STT retry X/4 — 429 Too Many Requests`
- **Line:** 101
- **Cause:** Exceeded Groq free tier limit (7,200 audio seconds/day, 20 req/min)
- **Fix:** Script auto-retries with backoff (3s → 6s → 12s → 24s). Just wait. Or retry the next day.

---

### ❌ `STT retry X/4 — model_decommissioned`
- **Line:** 101
- **Cause:** Groq renamed the model `whisper-large-v3-turbo`
- **Fix:** Update model name in `main.py` line 93. Check current models at [console.groq.com/docs/models](https://console.groq.com/docs/models)

---

### ❌ `STT failed after 4 retries` + `No transcript was produced`
- **Lines:** 104, 173
- **Cause:** All retries exhausted — network issue or completely silent audio
- **Fix:**
  1. Check internet connection
  2. Check [status.groq.com](https://status.groq.com) for outages
  3. Ensure your audio actually contains speech

---

## 5. Groq API — Summarization

### ❌ `Summarization failed: 400 — model_decommissioned`
- **Line:** 133
- **Cause:** `llama-3.1-8b-instant` was renamed by Groq
- **Fix:** Update `main.py` line 113. Current valid models:
  - `llama-3.1-8b-instant` — fastest
  - `llama-3.3-70b-versatile` — most accurate

---

### ❌ `Summarization failed: 413 Request Entity Too Large`
- **Line:** 133
- **Cause:** Transcript too long for 8k context window of `llama-3.1-8b-instant`
- **Fix:** Switch model in `main.py` line 113:
```python
model="llama-3.3-70b-versatile",   # 128k context window
```

---

## 6. Temp File / Disk

### ❌ `PermissionError` on `os.remove()`
- **Line:** 165
- **Cause:** Chunk file locked by Windows
- **Fix:**
```powershell
Remove-Item temp_chunks -Recurse -Force
```

---

### ❌ `OSError: [Errno 28] No space left on device`
- **Line:** 157
- **Cause:** Disk is full (each 45s chunk is only ~300 KB)
- **Fix:** Free up disk space and re-run

---

## 7. Webhook (Make.com)

### ❌ `Webhook failed: ConnectionError` / `Timeout`
- **Line:** 241
- **Cause:** URL is wrong/expired, or the Make.com scenario is paused
- **Fix:**
  1. Go to Make.com → your scenario → copy the fresh webhook URL
  2. Ensure the scenario is **Active**
  3. Re-run with the correct URL:
  ```powershell
  venv\Scripts\python main.py --mic --webhook "https://hook.eu1.make.com/xxxxx"
  ```

---

## ⚡ Quick Diagnostic Checklist

Run these in order when something breaks:

```powershell
# 1. Is venv Python working?
venv\Scripts\python --version

# 2. Is ffmpeg present?
dir venv\Scripts\ffmpeg.exe

# 3. Is the API key loaded?
venv\Scripts\python -c "from dotenv import load_dotenv; import os; load_dotenv(); k=os.getenv('GROQ_API_KEY'); print(k[:8] if k else 'NOT FOUND')"

# 4. Is the microphone detected?
venv\Scripts\python -c "import sounddevice as sd; print(sd.query_devices(kind='input'))"

# 5. Are all packages installed correctly?
venv\Scripts\pip check
```
