from flask import Flask, render_template, request, jsonify, session
from flask_session import Session
from dotenv import load_dotenv
import json
import os
import re
from openai import OpenAI
from pathlib import Path
import uuid

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
- No emojis, no bullets
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



# --------------------------------------------------
# TTS
# --------------------------------------------------
TTS_DIR = Path("static/tts")
TTS_DIR.mkdir(parents=True, exist_ok=True)

@app.route("/tts", methods=["POST"])
def tts():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()

    if not text:
        return jsonify({"error": "No text"}), 400

    try:
        voice = "verse" if detect_language(text) == "bn" else "alloy"
        audio_path = TTS_DIR / f"{uuid.uuid4().hex}.mp3"

        with client.audio.speech.with_streaming_response.create(
            model="gpt-4o-mini-tts",
            voice=voice,
            input=text,
            speed = 1.3) as response:
            response.stream_to_file(audio_path)

        return jsonify({"audio_url": f"/static/tts/{audio_path.name}"})

    except Exception as e:
        print("❌ TTS error:", e)
        return jsonify({"error": "TTS failed"}), 500


# --------------------------------------------------
# Run
# --------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
