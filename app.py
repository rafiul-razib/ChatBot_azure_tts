from flask import Flask, render_template, request, jsonify, session
from dotenv import load_dotenv
import google.generativeai as genai
import json
import os

# --------------------------------------------------
# Setup
# --------------------------------------------------
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret")

# Configure Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash")

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

print("✅ Brands loaded:", len(PRODUCT_DATA.get("brands", [])))

# --------------------------------------------------
# Load company article / info text
# --------------------------------------------------
try:
    with open(ARTICLE_PATH, "r", encoding="utf-8") as f:
        ARTICLE_TEXT = f.read()
except Exception as e:
    print("❌ Failed to load article.txt:", e)
    ARTICLE_TEXT = ""

# --------------------------------------------------
# Utility functions
# --------------------------------------------------
def get_all_products():
    """Flatten all products across brands"""
    products = []
    for brand in PRODUCT_DATA.get("brands", []):
        brand_name = brand.get("brand_name", "Unknown Brand")
        for product in brand.get("products", []):
            product_copy = product.copy()
            product_copy["brand"] = brand_name
            products.append(product_copy)
    return products


def format_products_for_prompt(products):
    """Prepare product info for AI prompt"""
    formatted = ""
    for p in products:
        formatted += f"""
Product Name: {p.get('name', 'N/A')}
Brand: {p.get('brand', 'N/A')}
Category: {p.get('category', 'N/A')}
Features: {p.get('features', 'N/A')}
Usage Instructions: {p.get('usage_instructions', 'N/A')}
Ingredients: {', '.join(p.get('ingredients', []))}
Price: {p.get('price_bdt', 'N/A')} BDT
Suitability: {p.get('suitability', 'N/A')}
---
"""
    return formatted

# --------------------------------------------------
# Routes
# --------------------------------------------------
@app.route("/")
def home():
    return render_template("index.html")

# @app.route("/")
# def home():
#     return "HTML route working 🚀"



@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    user_message = data.get("message", "").strip()
    temperature = float(data.get("temperature", 0.4))  # Get temperature from frontend if provided

    if not user_message:
        return jsonify({"reply": "Please ask a question! 😊"})

    # Initialize chat session history
    if "chat_history" not in session:
        session["chat_history"] = []

    # Prepare system instruction with company info and products
    if "system_instruction" not in session:
        products_context = format_products_for_prompt(get_all_products())
        session["system_instruction"] = f"""
You are a professional customer service officer for Lira Cosmetics Ltd.

Company Info:
{ARTICLE_TEXT}

Products:
{products_context}

Rules:
- Answer ONLY based on this data.
- Be clear, polite, and customer-friendly.
- Do NOT invent information.
"""

    system_instruction = session["system_instruction"]

    try:
        # Start the chat with history
        chat_obj = model.start_chat(history=session["chat_history"])

        # Send system instruction once per session
        if not session.get("system_sent", False):
            chat_obj.send_message(
                system_instruction,
                generation_config={
                    "temperature": temperature,
                    "top_p": 0.9,
                    "top_k": 40,
                    "max_output_tokens": 512
                }
            )
            session["system_sent"] = True

        # Send the actual user question
        response = chat_obj.send_message(
            user_message,
            generation_config={
                "temperature": temperature,
                "top_p": 0.9,
                "top_k": 40,
                "max_output_tokens": 512
            }
        )

        reply = response.text.strip()

        # Save updated chat history as JSON-serializable list
        new_history = []
        for msg in chat_obj.history:
            parts = [{"text": part.text} for part in msg.parts]
            new_history.append({"role": msg.role, "parts": parts})
        session["chat_history"] = new_history

    except Exception as e:
        print("❌ Gemini error:", e)
        reply = "I'm having trouble answering right now. Please try again."

    return jsonify({"reply": reply})


# --------------------------------------------------
# Run App
# --------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
