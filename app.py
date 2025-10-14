from flask import Flask, request, jsonify
from flask_cors import CORS
import google.generativeai as genai
import PyPDF2
import docx
import io
import os
import json
import traceback

# -----------------------------
# Flask initialization
# -----------------------------
app = Flask(__name__)
CORS(app)

# -----------------------------
# Gemini API Configuration
# -----------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("⚠️  WARNING: GEMINI_API_KEY not found in environment variables")
genai.configure(api_key=GEMINI_API_KEY)

# -----------------------------
# Model selection (updated for Oct 2025)
# -----------------------------
MODELS_TO_TRY = [
    "models/gemini-1.5-pro-latest",
    "models/gemini-1.5-flash-latest",
    "models/gemini-1.5-pro",
    "models/gemini-1.5-flash",
]

def get_working_model():
    """Try to initialize the first working Gemini model"""
    for model_name in MODELS_TO_TRY:
        try:
            print(f"🔍 Trying model: {model_name}")
            model = genai.GenerativeModel(model_name)
            # Simple test query
            response = model.generate_content("Hello, Gemini!")
            if response and response.text:
                print(f"✅ Model initialized successfully: {model_name}")
                return model, model_name
        except Exception as e:
            print(f"❌ Failed with {model_name}: {str(e)}")
            continue
    return None, None

print("🚀 Initializing Gemini model...")
model, active_model_name = get_working_model()
if model is None:
    print("⚠️  WARNING: No working model found! Will retry on first request.")
    active_model_name = "not initialized"

# -----------------------------
# File parsing helpers
# -----------------------------
def extract_text_from_pdf(file_content):
    try:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_content))
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        print(f"Error extracting PDF: {e}")
        return ""

def extract_text_from_docx(file_content):
    try:
        doc = docx.Document(io.BytesIO(file_content))
        text = "\n".join([p.text for p in doc.paragraphs])
        return text
    except Exception as e:
        print(f"Error extracting DOCX: {e}")
        return ""

# -----------------------------
# Routes
# -----------------------------
@app.route("/")
def home():
    return jsonify({
        "status": "ok",
        "message": "Resume Analyzer API is running!",
        "version": "5.1",
        "model": active_model_name,
        "api_key_set": "Yes" if GEMINI_API_KEY else "No"
    })

@app.route("/test-models", methods=["GET"])
def test_models():
    """Check which Gemini models are available"""
    results = {}
    for name in MODELS_TO_TRY:
        try:
            test_model = genai.GenerativeModel(name)
            r = test_model.generate_content("Test")
            results[name] = "✅ Working"
        except Exception as e:
            results[name] = f"❌ {str(e)[:120]}"
    return jsonify(results)

@app.route("/analyze", methods=["POST"])
def analyze_resumes():
    global model, active_model_name
    try:
        # Ensure model is initialized
        if model is None:
            print("Model not initialized, retrying...")
            model, active_model_name = get_working_model()
            if model is None:
                return jsonify({"error": "Не удалось инициализировать AI модель. Проверьте API ключ."}), 500

        files = request.files.getlist("resumes")
        criteria = request.form.get("criteria", "")

        if not files:
            return jsonify({"error": "Файлы не загружены"}), 400

        print(f"📄 Received {len(files)} files for analysis")

        resumes_data = []
        for idx, file in enumerate(files):
            filename = file.filename
            file_content = file.read()
            text = ""

            if filename.lower().endswith(".pdf"):
                text = extract_text_from_pdf(file_content)
            elif filename.lower().endswith(".docx"):
                text = extract_text_from_docx(file_content)
            elif filename.lower().endswith(".txt"):
                text = file_content.decode("utf-8", errors="ignore")

            if text.strip():
                resumes_data.append({
                    "id": idx + 1,
                    "filename": filename,
                    "text": text[:5000]
                })
                print(f"✅ Processed: {filename} ({len(text)} chars)")

        if not resumes_data:
            return jsonify({"error": "Не удалось извлечь текст из файлов"}), 400

        if len(resumes_data) > 10:
            resumes_data = resumes_data[:10]
            print("⚠️ Limited to 10 resumes for stability")

        # Prompt for Gemini
        prompt = f"""Ты — эксперт HR. Проанализируй резюме и выбери ТОП-5 кандидатов.

Критерии отбора: {criteria if criteria else "Квалификация, опыт, образование"}.

Резюме:
"""
        for resume in resumes_data:
            prompt += f"\n[#{resume['id']}] {resume['filename']}\n{resume['text']}\n---\n"

        prompt += """
Формат JSON-ответа (без markdown-разметки):
{
  "top_candidates": [
    {
      "rank": 1,
      "resume_id": 1,
      "filename": "имя файла",
      "score": 95,
      "strengths": ["сила 1", "сила 2"],
      "reasons": "Объяснение выбора",
      "key_skills": ["навык 1", "навык 2"]
    }
  ],
  "summary": "Общее резюме"
}
"""

        print(f"🤖 Sending to Gemini ({active_model_name})...")
        response = model.generate_content(prompt)
        result_text = response.text.strip()
        print(f"✅ Received response ({len(result_text)} chars)")

        # Cleanup possible markdown fences
        for prefix in ["```json", "```"]:
            if result_text.startswith(prefix):
                result_text = result_text[len(prefix):]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
        result_text = result_text.strip()

        try:
            result = json.loads(result_text)
            result["top_candidates"] = result.get("top_candidates", [])[:5]
            print(f"🎯 Parsed {len(result['top_candidates'])} candidates successfully")
            return jsonify(result)
        except json.JSONDecodeError:
            return jsonify({
                "raw_response": result_text,
                "note": "Ответ не в JSON-формате"
            })

    except Exception as e:
        print(f"🔥 Error: {str(e)}")
        traceback.print_exc()
        return jsonify({"error": f"Ошибка: {str(e)}"}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "model": active_model_name
    }), 200

# -----------------------------
# Run app
# -----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"🌐 Starting server on port {port} (model: {active_model_name})")
    app.run(host="0.0.0.0", port=port, debug=False)
