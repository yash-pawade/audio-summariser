3
# 📦 Required Packages

All packages needed to run `main.py`.

## Install Command

```powershell
venv\Scripts\pip install -r requirements.txt
```

---

## Direct Dependencies

| Package | Version | Purpose |
|---|---|---|
| `groq` | 1.1.2 | Whisper STT + LLaMA summarization via Groq API |
| `pydub` | 0.25.1 | Load and chunk audio files (mp3, wav, m4a, etc.) |
| `python-dotenv` | 1.0.1 | Load `GROQ_API_KEY` from `.env` file |
| `requests` | 2.31.0 | Send summary to Make.com webhook |
| `sounddevice` | 0.5.5 | Record live audio from microphone |
| `soundfile` | 0.13.1 | Save recorded mic audio to WAV |

---

## Auto-Installed Dependencies

> These are pulled in automatically — you do NOT need to add them to `requirements.txt`.

| Package | Pulled in by |
|---|---|
| `numpy` | `soundfile` |
| `httpx` | `groq` |
| `pydantic` | `groq` |
| `anyio` | `groq` |
| `cffi` | `sounddevice` |
| `distro`, `sniffio`, `h11`, `httpcore` | `groq` |
| `certifi`, `idna`, `charset-normalizer`, `urllib3` | `requests` |

---

## Non-Python Dependency

| Tool | Purpose | Location after setup |
|---|---|---|
| `ffmpeg` | Decode audio files for pydub | `venv\Scripts\ffmpeg.exe` |

> ffmpeg is **NOT** installed via pip. It must be copied manually to `venv\Scripts\`.  
> See `ERRORS.md` for the download command if it's missing.

---

## Verify All Packages Are Installed

```powershell
venv\Scripts\pip check
venv\Scripts\pip list --format=freeze
```
