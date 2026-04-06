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

    clean_content_type = f"audio/{ext}"
    prompt_text = request.form.get("prompt", "").strip()
    
    # Hardcoded base context for Whisper STT
    base_prompt = "Indian English accent. Ignore background noise and focus purely on speech. Correctly identify names after phrases like 'my name is'. Accuracy is top priority. "
    full_prompt = base_prompt + prompt_text
    
    kwargs = {
        "file": (f"chunk.{ext}", audio_bytes, clean_content_type),
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
                        "You are a meticulous AI summarizer focusing on high accuracy. "
                        "When analyzing the transcript: "
                        "1. Focus strictly on speakers with Indian accents. "
                        "2. Ignore background noise or hallucinated artifacts from audio artifacts. "
                        "3. If someone says 'my name is', treat the following term as a name and analyze it properly. "
                        "4. Provide a clear, structured summary in bullet points (•) highlighting key topics and action items. "
                        "Maximum accuracy is required."
                    ),
                },
                {"role": "user", "content": f"Summarise:\n\n{transcript}"},
            ],
            temperature=0.3,
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
