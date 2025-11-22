# app.py
import os
import json
import time
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv

load_dotenv()

# Optional libs (may not be installed)
HAVE_TRANSFORMERS = False
HAVE_GOOGLETRANS = False
try:
    from transformers import pipeline, AutoTokenizer, AutoModelForSeq2SeqLM
    HAVE_TRANSFORMERS = True
except Exception:
    HAVE_TRANSFORMERS = False

try:
    # googletrans fallback for easy no-key usage
    from googletrans import Translator as GoogleTranslator
    HAVE_GOOGLETRANS = True
except Exception:
    HAVE_GOOGLETRANS = False

import requests

app = Flask(__name__, static_folder="static", template_folder="templates")

# env
HF_API_KEY = os.getenv("HUGGINGFACE_API_KEY")  # optional
HF_API_URL = "https://api-inference.huggingface.co/models/{}"
# Which model to try first when using HF inference (Helsinki family)
HELSINKI_PREFIX = "Helsinki-NLP/opus-mt-{}-{}"  # src-tgt

# If you want to run local models, you can set this to True (requires large install)
USE_LOCAL_TRANSFORMERS = os.getenv("USE_LOCAL_TRANSFORMERS", "0") in ("1", "true", "True")

# create googletrans translator if available
google_translator = GoogleTranslator() if HAVE_GOOGLETRANS else None

# Minimal language map — adjust as needed
# Helsinki models use 2-letter codes (en, es, hi, ta, fr...)
SUPPORTED = {
    "en", "es", "hi", "ta", "fr", "de", "pt", "it", "nl", "ru", "ar", "bn", "ur"
}

def call_hf_inference(model_name: str, text: str, timeout=30):
    """
    Calls Hugging Face Inference API for translation.
    Returns translated text on success or raises an exception.
    """
    url = HF_API_URL.format(model_name)
    headers = {"Authorization": f"Bearer {HF_API_KEY}"} if HF_API_KEY else {}
    payload = {"inputs": text}
    # For some translation models we can pass parameters
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except Exception as e:
        raise RuntimeError(f"HF request failed: {e}")
    if resp.status_code == 503:
        raise RuntimeError("HF model is loading or service unavailable (503).")
    if not resp.ok:
        raise RuntimeError(f"HF error {resp.status_code}: {resp.text}")
    data = resp.json()
    # HF typically returns [{"translation_text": "..."}] for translation models,
    # or a plain string/object for other models. Try robust parsing.
    if isinstance(data, list) and data and isinstance(data[0], dict):
        # e.g. [{"translation_text":"..."}]
        for key in ("translation_text", "translated_text", "text"):
            if key in data[0]:
                return data[0][key]
        # fallback: join any string values
        text_vals = [v for v in data[0].values() if isinstance(v, str)]
        if text_vals:
            return text_vals[0]
        return json.dumps(data[0])
    if isinstance(data, dict):
        # sometimes an object
        for v in data.values():
            if isinstance(v, str):
                return v
        return json.dumps(data)
    if isinstance(data, str):
        return data
    # last resort
    return str(data)

def translate_local_transformers(model_name: str, text: str):
    """
    Use local transformers to translate. This will download model if necessary.
    Requires 'transformers' and a backend like torch.
    """
    if not HAVE_TRANSFORMERS:
        raise RuntimeError("transformers not available locally.")
    # instantiate pipeline each call may be heavy; in a production app cache this
    pipe = pipeline("translation", model=model_name)
    out = pipe(text, max_length=1024)
    if isinstance(out, list) and out and "translation_text" in out[0]:
        return out[0]["translation_text"]
    if isinstance(out, list) and out and isinstance(out[0], dict):
        # different keys
        return list(out[0].values())[0]
    return str(out)

def translate_googletrans(text: str, src: str, tgt: str):
    """
    Fallback translator using googletrans (no API key)
    """
    if not HAVE_GOOGLETRANS:
        raise RuntimeError("googletrans not installed.")
    # googletrans supports src='auto'
    src_arg = None if src == "auto" else src
    res = google_translator.translate(text, src=src_arg, dest=tgt)
    return getattr(res, "text", str(res)), getattr(res, "src", None)

@app.route("/")
def index():
    # regen languages for client if desired
    return render_template("index.html")

@app.route("/translate", methods=["POST"])
def translate_route():
    data = request.json or {}
    text = data.get("text", "").strip()
    source = data.get("source", "auto")
    target = data.get("target", "en")

    if not text:
        return jsonify({"error": "empty_text"}), 400

    # normalize codes: take first two letters lowercase
    s = source if source != "auto" else "auto"
    t = target.lower()

    # If requested target not in our SUPPORTED set, fallback to googletrans path
    try_models_first = True

    # Try Hugging Face Inference API if key present
    hf_model_name = None
    translated_text = None
    detected_src = None

    # Determine candidate HF model if possible
    if s != "auto" and s in SUPPORTED and t in SUPPORTED:
        hf_model_name = HELSINKI_PREFIX.format(s, t)
    elif s == "auto" and t in SUPPORTED:
        # assume english source if auto and we can't detect earlier
        hf_model_name = HELSINKI_PREFIX.format("en", t)

    # 1) Try HF Inference API
    if HF_API_KEY and hf_model_name:
        try:
            translated_text = call_hf_inference(hf_model_name, text)
            return jsonify({"translated": translated_text, "used": "huggingface_inference", "model": hf_model_name})
        except Exception as e:
            # continue to next fallback
            # don't leak full stack, but include message
            print("HF inference failed:", e)

    # 2) If requested/available: try local transformers
    if USE_LOCAL_TRANSFORMERS and HAVE_TRANSFORMERS and hf_model_name:
        try:
            translated_text = translate_local_transformers(hf_model_name, text)
            return jsonify({"translated": translated_text, "used": "local_transformers", "model": hf_model_name})
        except Exception as e:
            print("Local transformers failed:", e)

    # 3) Fallback to googletrans if installed
    if HAVE_GOOGLETRANS:
        try:
            translated_text, detected_src = translate_googletrans(text, s, t)
            return jsonify({"translated": translated_text, "used": "googletrans_fallback", "detected_src": detected_src})
        except Exception as e:
            print("googletrans failed:", e)

    # 4) If everything failed, return an error
    return jsonify({"error": "translation_unavailable", "detail": "No translation backend available. Install transformers/torch or set HUGGINGFACE_API_KEY, or install googletrans."}), 500

@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "time": time.time()})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
