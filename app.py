from flask import Flask, render_template, request, jsonify, session
from flask_session import Session
from dotenv import load_dotenv
import json
import os
import re
from openai import OpenAI
from pathlib import Path
import uuid
import azure.cognitiveservices.speech as speechsdk

# --------------------------------------------------
# Setup
# --------------------------------------------------
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret")

# 🔥 SERVER-SIDE SESSION CONFIG
app.config.update(
    SESSION_TYPE="filesystem",
    SESSION_PERMANENT=False,
    SESSION_USE_SIGNER=True,
    SESSION_FILE_DIR=os.path.join(os.getcwd(), "flask_sessions"),
    SESSION_FILE_THRESHOLD=500
)

Session(app)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --------------------------------------------------
# Paths
# --------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_PATH = os.path.join(BASE_DIR, "products.json")
ARTICLE_PATH = os.path.join(BASE_DIR, "article.txt")

# --------------------------------------------------
# Load product data
# --------------------------------------------------
try:
    with open(PRODUCTS_PATH, "r", encoding="utf-8") as f:
        PRODUCT_DATA = json.load(f)
except Exception as e:
    print("❌ Failed to load products.json:", e)
    PRODUCT_DATA = {"brands": []}

# --------------------------------------------------
# Load company article
# --------------------------------------------------
try:
    with open(ARTICLE_PATH, "r", encoding="utf-8") as f:
        ARTICLE_TEXT = f.read()
except Exception as e:
    print("❌ Failed to load article.txt:", e)
    ARTICLE_TEXT = ""

# --------------------------------------------------
# Utilities
# --------------------------------------------------
def detect_language(text):
    return "bn" if re.search(r"[\u0980-\u09FF]", text) else "en"

def get_all_products():
    products = []
    for brand in PRODUCT_DATA.get("brands", []):
        for product in brand.get("products", []):
            p = product.copy()
            p["brand"] = brand.get("brand_name", "Unknown Brand")
            products.append(p)
    return products

def format_products_for_prompt(products):
    return "\n".join(
        f"""Product Name: {p.get('name')}
Brand: {p.get('brand')}
Category: {p.get('category')}
Features: {p.get('features')}
Usage: {p.get('usage_instructions')}
Ingredients: {', '.join(p.get('ingredients', []))}
Price: {p.get('price_bdt')} BDT
Suitability: {p.get('suitability')}
---"""
        for p in products
    )
# --------------------------------------------------
# TTS Utilities (Improved Bangla Voice with Expression)
# --------------------------------------------------
import random
import re
import os
import uuid
from pathlib import Path
import azure.cognitiveservices.speech as speechsdk

TTS_DIR = Path("static/tts")
TTS_DIR.mkdir(parents=True, exist_ok=True)

def build_ssml(text, lang):
    """
    Build SSML for more natural speech.
    - Bangla: expressive style, dynamic pitch/rate, sentence-level prosody, emphasis
    - English: cheerful style
    """
    if lang == "bn":
        # Split text into sentences and add pauses
        sentences = re.split(r'(?<=[।!?])', text)
        ssml_text = ""
        for s in sentences:
            if s.strip():
                # Longer pause for strong punctuation
                if s.strip().endswith(("!", "?")):
                    ssml_text += f"<prosody pitch='{random.choice(['+2%', '+3%', '+4%'])}' rate='{random.choice(['1.03','1.05','1.07'])}'>{s.strip()}</prosody> <break time='500ms'/> "
                else:
                    ssml_text += f"<prosody pitch='{random.choice(['+1%', '+2%', '+3%'])}' rate='{random.choice(['1.02','1.04','1.06'])}'>{s.strip()}</prosody> <break time='250ms'/> "

        return f"""
<speak version="1.0"
       xmlns="http://www.w3.org/2001/10/synthesis"
       xmlns:mstts="http://www.w3.org/2001/mstts"
       xml:lang="bn-BD">
  <voice name="bn-BD-NabanitaNeural">
    <mstts:express-as style="chat">
      {ssml_text}
    </mstts:express-as>
  </voice>
</speak>
"""
    else:
        voice = "en-US-JennyNeural"
        return f"""
<speak version="1.0"
       xmlns="http://www.w3.org/2001/10/synthesis"
       xmlns:mstts="http://www.w3.org/2001/mstts"
       xml:lang="en-US">
  <voice name="{voice}">
    <mstts:express-as style="cheerful" styledegree="1.2">
      <prosody rate="1.05" pitch="+3%">
        {text}
      </prosody>
    </mstts:express-as>
  </voice>
</speak>
"""

def synthesize_speech(text, lang):
    """
    Generate TTS audio from text using Azure Speech (improved Bangla)
    """
    speech_key = os.getenv("AZURE_SPEECH_KEY")
    service_region = os.getenv("AZURE_SPEECH_REGION")

    if not speech_key or not service_region:
        raise RuntimeError("Azure Speech credentials missing")

    speech_config = speechsdk.SpeechConfig(
        subscription=speech_key,
        region=service_region
    )

    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
    )

    audio_path = TTS_DIR / f"{uuid.uuid4().hex}.mp3"
    audio_config = speechsdk.audio.AudioOutputConfig(filename=str(audio_path))

    synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config,
        audio_config=audio_config
    )

    ssml = build_ssml(text, lang)
    result = synthesizer.speak_ssml_async(ssml).get()

    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        raise RuntimeError("Azure TTS failed")

    return audio_path

# --------------------------------------------------
# Routes
# --------------------------------------------------
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"reply": "Please ask a question.", "lang": "en"})

    lang = detect_language(user_message)

    if "chat_history" not in session:
        session["chat_history"] = []

    if "system_instruction" not in session:
        session["system_instruction"] = f"""
You are a professional customer service officer for Lira Cosmetics Ltd.

Company Info:
{ARTICLE_TEXT}

Products:
{format_products_for_prompt(get_all_products())}
"""

    system_rules = (
        "Reply in polite, natural Bangla."
        if lang == "bn"
        else "Reply in polite, natural English."
    )

    messages = [
        {"role": "system", "content": session["system_instruction"]},
        {
            "role": "system",
            "content": f"""{system_rules}
Rules:
- Answer ONLY from company data
- Keep replies short (2–3 sentences)
- No emojis, no bullets and numbering
- instead of BDT say টাকা
- Any numbers in the reply should be stated as numbers, not words. Like reply ৮৫০ instead of ৮50
"""
        },
        *session["chat_history"],
        {"role": "user", "content": user_message},
    ]

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=200
        )

        reply = response.choices[0].message.content.strip()

        # Keep last 3 turns
        session["chat_history"] = (
            session["chat_history"] +
            [{"role": "user", "content": user_message},
             {"role": "assistant", "content": reply}]
        )[-6:]

    except Exception as e:
        print("❌ OpenAI error:", e)
        reply = (
            "এই মুহূর্তে উত্তর দিতে সমস্যা হচ্ছে।"
            if lang == "bn"
            else "I'm having trouble answering right now."
        )

    return jsonify({"reply": reply, "lang": lang})

@app.route("/tts", methods=["POST"])
def tts():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    lang = data.get("lang")  # optional override from client

    if not text:
        return jsonify({"error": "No text provided"}), 400

    try:
        # Normalize language codes
        if not lang:
            lang = detect_language(text)
        if lang.lower() in ["bn", "bn-bd", "bn_bd"]:
            lang = "bn"

        audio_path = synthesize_speech(text, lang)

        return jsonify({
            "audio_url": f"/static/tts/{audio_path.name}",
            "lang": lang
        })

    except Exception as e:
        print("❌ Azure TTS error:", e)
        return jsonify({"error": f"TTS failed: {str(e)}"}), 500

# --------------------------------------------------
# Run
# --------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
