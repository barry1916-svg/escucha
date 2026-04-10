"""
Escucha — Spanish Listening Comprehension App
"""
import asyncio
import io
import os
import random
import sys

import edge_tts
from flask import Flask, jsonify, render_template, request, send_file
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sentences import SENTENCES, TENSES

app = Flask(__name__)

VOICE = "es-ES-AlvaroNeural"
_audio_cache: dict = {}


async def _tts_bytes(text: str) -> bytes:
    communicate = edge_tts.Communicate(text, VOICE)
    buf = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf += chunk["data"]
    return buf


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/question")
def question():
    exclude_param = request.args.get("exclude", "")
    exclude_ids = {int(x) for x in exclude_param.split(",") if x.strip().isdigit()}
    pool = [s for s in SENTENCES if s["id"] not in exclude_ids] or SENTENCES[:]
    sentence = random.choice(pool)

    wrong = random.sample([t for t in TENSES if t != sentence["tense"]], 3)
    choices = wrong + [sentence["tense"]]
    random.shuffle(choices)

    return jsonify({"id": sentence["id"], "choices": choices})


@app.route("/api/audio/<int:sentence_id>")
def audio(sentence_id):
    sentence = next((s for s in SENTENCES if s["id"] == sentence_id), None)
    if not sentence:
        return "Not found", 404

    if sentence_id not in _audio_cache:
        try:
            _audio_cache[sentence_id] = asyncio.run(_tts_bytes(sentence["spanish"]))
        except Exception as exc:
            return f"TTS error: {exc}", 503

    resp = send_file(
        io.BytesIO(_audio_cache[sentence_id]),
        mimetype="audio/mpeg",
        as_attachment=False,
    )
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@app.route("/api/check", methods=["POST"])
def check():
    body = request.get_json(silent=True) or {}
    sentence_id = body.get("id")
    answer = body.get("answer")
    sentence = next((s for s in SENTENCES if s["id"] == sentence_id), None)
    if not sentence:
        return jsonify({"error": "Not found"}), 404

    correct = answer == sentence["tense"]
    return jsonify({
        "correct": correct,
        "correct_answer": sentence["tense"],
        "spanish": sentence["spanish"],
        "english": sentence["english"],
        "verb_form": sentence["verb_form"],
        "verb_infinitive": sentence["verb_infinitive"],
        "explanation": sentence["explanation"],
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=True, port=port)
