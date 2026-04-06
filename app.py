"""
Flask web server for Real-Time Mic Summarizer.
Run:  python app.py
Then open http://localhost:5000
"""

import os
import logging
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

for lib in ("httpx", "httpcore", "groq"):
    logging.getLogger(lib).setLevel(logging.ERROR)

app = Flask(__name__)
CORS(app)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
client = Groq(api_key=GROQ_API_KEY)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "api_key_set": bool(GROQ_API_KEY)})


@app.route("/api/transcribe", methods=["POST"])
def transcribe():
    if "audio" not in request.files:
        return jsonify({"error": "No audio provided"}), 400

    audio_file = request.files["audio"]
    audio_bytes = audio_file.read()

    if len(audio_bytes) < 500:
        return jsonify({"transcript": "", "skipped": True})

    content_type = audio_file.content_type or "audio/webm"
    ext = content_type.split("/")[-1].split(";")[0]
    if ext not in ("webm", "mp4", "ogg", "wav", "mp3"):
        ext = "webm"

    from pydub import AudioSegment
    from pydub.silence import split_on_silence
    import io

    # Load into Pydub for high-accuracy preprocessing (normalizing + resampling)
    try:
        audio_io = io.BytesIO(audio_bytes)
        segment = AudioSegment.from_file(audio_io)
        
        # Optimize for Whisper: 16kHz, Mono, Normalized
        segment = segment.set_frame_rate(16000).set_channels(1)
        # Normalize to prevent transcription issues with low/high volume
        normalized_segment = segment.normalize()

        # --- Frequency Bandpass Filtering (isolate human voice: 300Hz–3400Hz) ---
        # High-pass removes low-frequency rumble, table thumps, AC hum, wind
        filtered_segment = normalized_segment.high_pass_filter(300)
        # Low-pass removes high-frequency hiss, electronic static, sibilance artifacts
        filtered_segment = filtered_segment.low_pass_filter(3400)

        # --- Silence Stripping (prevents Whisper hallucinations on quiet gaps) ---
        chunks = split_on_silence(
            filtered_segment,
            min_silence_len=500,   # treat 500ms+ of quiet as silence
            silence_thresh=-40,    # silence threshold in dBFS
            keep_silence=200       # retain 200ms padding so words don't run together
        )
        # Re-join speech chunks; fall back to full filtered segment if no split found
        if chunks:
            filtered_segment = sum(chunks)

        # Export precisely as FLAC (lossless) for maximum Groq accuracy
        out_io = io.BytesIO()
        filtered_segment.export(out_io, format="flac")
        processed_audio_bytes = out_io.getvalue()
        processed_content_type = "audio/flac"
        processed_ext = "flac"
    except Exception as e:
        print(f"Pydub Error (falling back to raw): {e}")
        processed_audio_bytes = audio_bytes
        processed_content_type = f"audio/{ext}"
        processed_ext = ext

    prompt_text = request.form.get("prompt", "").strip()
    
    # Hardcoded context for Whisper STT (Indian context + naming focus)
    base_prompt = "Indian English accent. Focus on Indian naming conventions. Ignore background noise and focus purely on speech accurately. Correctly identify names after phrases like 'my name is'. "
    full_prompt = base_prompt + prompt_text
    
    kwargs = {
        "file": (f"chunk.{processed_ext}", processed_audio_bytes, processed_content_type),
        "model": "whisper-large-v3-turbo",
        "response_format": "text",
        "language": "en",
        "prompt": full_prompt[-500:] # Whisper prompt limit
    }

    try:
        rsp = client.audio.transcriptions.create(**kwargs)
        text = (rsp if isinstance(rsp, str) else str(rsp)).strip()
        return jsonify({"transcript": text})
    except Exception as exc:
        print(f"STT Error: {exc}")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/summarize", methods=["POST"])
def summarize():
    data = request.get_json(force=True)
    transcript = data.get("transcript", "").strip()

    if not transcript:
        return jsonify({"summary": ""})

    try:
        rsp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a meticulous AI transcription corrector and summarizer. "
                        "Follow these steps in order:\n"
                        "1. CORRECT: Silently fix obvious phonetic/STT errors based on context "
                        "(e.g., 'going true the store' → 'going through the store', "
                        "'there' vs 'their' vs 'they're'). Do NOT output the corrected text, just use it internally.\n"
                        "2. NAMES: Speakers may have an Indian accent. If someone says 'my name is', "
                        "treat the next word(s) as a proper name and retain the most phonetically "
                        "accurate Indian spelling (e.g., Yash, Diya, Arjun, Priya). "
                        "DO NOT mention the accent in your output.\n"
                        "3. FILTER: Discard any hallucinated audio artifacts, repeated filler words, "
                        "or background noise transcriptions (e.g., '[MUSIC]', 'um', 'uh', lone syllables).\n"
                        "4. SUMMARIZE: Provide a concise, structured summary in bullet points (•). "
                        "Each bullet should capture one clear idea. Accuracy is the top priority."
                    ),
                },
                {"role": "user", "content": f"Summarise:\n\n{transcript}"},
            ],
            temperature=0.2,
            max_tokens=400,
        )
        return jsonify({"summary": rsp.choices[0].message.content.strip()})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    print("\n  🎙  Real-Time Mic Summarizer")
    print("  ────────────────────────────")
    print("  → http://localhost:5000\n")
    app.run(debug=False, port=5000, threaded=True)
