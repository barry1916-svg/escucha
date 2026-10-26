"""
Escucha — Spanish Listening Comprehension App
"""
import asyncio
import io
import os
import random
import re
import sys

import edge_tts
from flask import Flask, jsonify, render_template, request, send_file
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sentences import SENTENCES, TENSES, CANDIDATE_TENSES
from phrases import PHRASES
from wishes import WISHES
from fill_blanks import FILL_SENTENCES, FILL_TENSES

app = Flask(__name__)

VOICE = "es-ES-AlvaroNeural"
_audio_cache: dict = {}

ORDINALS = ["first", "second", "third", "fourth", "fifth",
            "sixth", "seventh", "eighth", "ninth", "tenth"]


def verb_position_label(spanish: str, verb_form: str) -> str:
    """Return ordinal word-position label for the target verb, e.g. 'third word'."""
    words = re.sub(r"[¿?¡!,.:;«»\"'()]", "", spanish).lower().split()
    target = verb_form.lower().split()[0]  # first token for compound forms
    try:
        idx = words.index(target)
        ordinal = ORDINALS[idx] if idx < len(ORDINALS) else f"{idx + 1}th"
        return f"{ordinal} word"
    except ValueError:
        return "the verb"


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

    tenses_param = request.args.get("tenses", "")
    active_tenses = [t for t in tenses_param.split(",") if t in CANDIDATE_TENSES]
    if len(active_tenses) != 4:
        active_tenses = random.sample(CANDIDATE_TENSES, 4)

    candidates = [s for s in SENTENCES if s["tense"] in active_tenses]
    pool = [s for s in candidates if s["id"] not in exclude_ids] or candidates
    sentence = random.choice(pool)

    choices = active_tenses[:]
    random.shuffle(choices)

    verb_label = verb_position_label(sentence["spanish"], sentence["verb_form"])
    return jsonify({
        "id": sentence["id"],
        "choices": choices,
        "verb_label": verb_label,
        "active_tenses": active_tenses,
    })


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


@app.route("/api/phrase")
def phrase():
    exclude_param = request.args.get("exclude", "")
    exclude_ids = {int(x) for x in exclude_param.split(",") if x.strip().isdigit()}
    pool = [p for p in PHRASES if p["id"] not in exclude_ids] or PHRASES[:]
    p = random.choice(pool)
    return jsonify({
        "id": p["id"],
        "sentence_es": p["sentence_es"],
        "sentence_en": p["sentence_en"],
        "phrase_es": p["phrase_es"],
        "phrase_en": p["phrase_en"],
    })


@app.route("/api/audio/phrase/<int:phrase_id>")
def phrase_audio(phrase_id):
    p = next((x for x in PHRASES if x["id"] == phrase_id), None)
    if not p:
        return "Not found", 404
    cache_key = f"phrase_{phrase_id}"
    if cache_key not in _audio_cache:
        try:
            _audio_cache[cache_key] = asyncio.run(_tts_bytes(p["sentence_es"]))
        except Exception as exc:
            return f"TTS error: {exc}", 503
    resp = send_file(
        io.BytesIO(_audio_cache[cache_key]),
        mimetype="audio/mpeg",
        as_attachment=False,
    )
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@app.route("/api/wishes")
def wishes():
    n = min(request.args.get("n", 8, type=int), len(WISHES))
    exclude_param = request.args.get("exclude", "")
    exclude_ids = {int(x) for x in exclude_param.split(",") if x.strip().isdigit()}

    def pick(pool, k):
        # Unseen items first; top up from seen ones only if the pool runs out.
        fresh = [w for w in pool if w["id"] not in exclude_ids]
        seen = [w for w in pool if w["id"] in exclude_ids]
        random.shuffle(fresh)
        random.shuffle(seen)
        return (fresh + seen)[:k]

    # About a quarter of each round are "trap" sentences that need the indicative.
    traps = [w for w in WISHES if w["rule"] == "indicativo"]
    others = [w for w in WISHES if w["rule"] != "indicativo"]
    n_traps = min(round(n / 4), len(traps))
    chosen = pick(traps, n_traps) + pick(others, n - n_traps)
    random.shuffle(chosen)
    return jsonify(chosen)


@app.route("/api/audio/wish/<int:wish_id>")
def wish_audio(wish_id):
    w = next((x for x in WISHES if x["id"] == wish_id), None)
    if not w:
        return "Not found", 404
    cache_key = f"wish_{wish_id}"
    if cache_key not in _audio_cache:
        try:
            _audio_cache[cache_key] = asyncio.run(_tts_bytes(w["es"]))
        except Exception as exc:
            return f"TTS error: {exc}", 503
    resp = send_file(
        io.BytesIO(_audio_cache[cache_key]),
        mimetype="audio/mpeg",
        as_attachment=False,
    )
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@app.route("/api/fill")
def fill():
    # One sentence per tense, preferring ones not in `exclude` (recently seen).
    exclude_param = request.args.get("exclude", "")
    exclude_ids = {int(x) for x in exclude_param.split(",") if x.strip().isdigit()}
    chosen = []
    for tense in FILL_TENSES:
        pool = [s for s in FILL_SENTENCES if s["tense"] == tense]
        fresh = [s for s in pool if s["id"] not in exclude_ids]
        chosen.append(random.choice(fresh or pool))
    random.shuffle(chosen)
    return jsonify(chosen)


@app.route("/api/audio/fill/<int:fill_id>")
def fill_audio(fill_id):
    s = next((x for x in FILL_SENTENCES if x["id"] == fill_id), None)
    if not s:
        return "Not found", 404
    cache_key = f"fill_{fill_id}"
    if cache_key not in _audio_cache:
        try:
            _audio_cache[cache_key] = asyncio.run(_tts_bytes(s["es"]))
        except Exception as exc:
            return f"TTS error: {exc}", 503
    resp = send_file(
        io.BytesIO(_audio_cache[cache_key]),
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
