from flask import Flask, request, jsonify
from flask_cors import CORS
import google.generativeai as genai
import PyPDF2
import docx
import io
import os
import json
import time

app = Flask(__name__)
CORS(app)

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', 'AIzaSyBrblYdHmCrrxLu3atlu1uhxvUvj8e9buM')
genai.configure(api_key=GEMINI_API_KEY)

# Список моделей для проверки (в порядке приоритета)
MODELS_TO_TRY = [
    'gemini-pro',
    'models/gemini-pro',
    'gemini-1.5-pro',
    'models/gemini-1.5-pro',
]

def get_working_model():
    """Находит рабочую модель"""
    for model_name in MODELS_TO_TRY:
        try:
            print(f"Trying model: {model_name}")
            model = genai.GenerativeModel(model_name)
            # Тестовый запрос
            response = model.generate_content("Hello")
            print(f"Success with model: {model_name}")
            return model, model_name
        except Exception as e:
            print(f"Failed with {model_name}: {str(e)}")
            continue
    return None, None

# Инициализируем модель при старте
print("Initializing Gemini model...")
model, active_model_name = get_working_model()

if model is None:
    print("WARNING: No working model found! Will try again on first request.")
    active_model_name = "not initialized"

def extract_text_from_pdf(file_content):
    try:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_content))
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text()
        return text
    except Exception as e:
        print(f"Error extracting PDF: {e}")
        return ""

def extract_text_from_docx(file_content):
    try:
        doc = docx.Document(io.BytesIO(file_content))
        text = "\n".join([para.text for para in doc.paragraphs])
        return text
    except Exception as e:
        print(f"Error extracting DOCX: {e}")
        return ""

@app.route('/')
def home():
    return jsonify({
        "status": "ok",
        "message": "Resume Analyzer API работает!",
        "version": "5.0",
        "model": active_model_name,
        "api_key_set": "Yes" if GEMINI_API_KEY else "No"
    })

@app.route('/test-models', methods=['GET'])
def test_models():
    """Тестирует все доступные модели"""
    results = {}
    for model_name in MODELS_TO_TRY:
        try:
            test_model = genai.GenerativeModel(model_name)
            response = test_model.generate_content("Test")
            results[model_name] = "✅ Working"
        except Exception as e:
            results[model_name] = f"❌ {str(e)[:100]}"
    return jsonify(results)

@app.route('/analyze', methods=['POST'])
def analyze_resumes():
    global model, active_model_name
    
    try:
        # Проверяем модель
        if model is None:
            print("Model not initialized, trying to initialize now...")
            model, active_model_name = get_working_model()
            if model is None:
                return jsonify({"error": "Не удалось инициализировать AI модель. Проверьте API ключ."}), 500
        
        files = request.files.getlist('resumes')
        criteria = request.form.get('criteria', '')
        
        if not files:
            return jsonify({"error": "Файлы не загружены"}), 400
        
        print(f"Received {len(files)} files for analysis")
        
        resumes_data = []
        for idx, file in enumerate(files):
            filename = file.filename
            file_content = file.read()
            
            text = ""
            if filename.lower().endswith('.pdf'):
                text = extract_text_from_pdf(file_content)
            elif filename.lower().endswith('.docx'):
                text = extract_text_from_docx(file_content)
            elif filename.lower().endswith('.txt'):
                text = file_content.decode('utf-8', errors='ignore')
            
            if text.strip():
                resumes_data.append({
                    "id": idx + 1,
                    "filename": filename,
                    "text": text[:5000]
                })
                print(f"Processed: {filename} ({len(text)} chars)")
        
        if not resumes_data:
            return jsonify({"error": "Не удалось извлечь текст из файлов"}), 400
        
        # Ограничиваем количество резюме для стабильности
        if len(resumes_data) > 10:
            resumes_data = resumes_data[:10]
            print(f"Limited to 10 resumes")
        
        prompt = f"""Ты эксперт HR. Проанализируй резюме и выбери ТОП-5.

Критерии: {criteria if criteria else "Квалификация, опыт, образование"}

Резюме:
"""
        
        for resume in resumes_data:
            prompt += f"\n[#{resume['id']}] {resume['filename']}\n{resume['text']}\n---\n"
        
        prompt += """
JSON ответ (без markdown):
{
  "top_candidates": [
    {
      "rank": 1,
      "resume_id": 1,
      "filename": "имя",
      "score": 95,
      "strengths": ["сила 1", "сила 2"],
      "reasons": "Объяснение",
      "key_skills": ["навык 1", "навык 2"]
    }
  ],
  "summary": "Общее резюме"
}
"""
        
        print(f"Sending to Gemini ({active_model_name})...")
        
        try:
            response = model.generate_content(prompt)
            result_text = response.text
            print(f"Got response: {len(result_text)} chars")
        except Exception as api_error:
            error_msg = str(api_error)
            print(f"Gemini error: {error_msg}")
            
            # Если ошибка 404, пробуем другую модель
            if "404" in error_msg or "not found" in error_msg:
                print("Trying to find alternative model...")
                model, active_model_name = get_working_model()
                if model:
                    try:
                        response = model.generate_content(prompt)
                        result_text = response.text
                        print(f"Success with alternative model: {active_model_name}")
                    except Exception as e2:
                        return jsonify({"error": f"Все модели недоступны: {str(e2)}"}), 500
                else:
                    return jsonify({"error": "Нет доступных моделей Gemini"}), 500
            else:
                return jsonify({"error": f"Ошибка API: {error_msg}"}), 500
        
        # Очистка ответа
        result_text = result_text.strip()
        for prefix in ['```json', '```']:
            if result_text.startswith(prefix):
                result_text = result_text[len(prefix):]
        if result_text.endswith('```'):
            result_text = result_text[:-3]
        result_text = result_text.strip()
        
        try:
            result = json.loads(result_text)
            if 'top_candidates' in result:
                result['top_candidates'] = result['top_candidates'][:5]
            print(f"Success! {len(result.get('top_candidates', []))} candidates")
            return jsonify(result)
        except json.JSONDecodeError:
            return jsonify({
                "raw_response": result_text,
                "note": "Текстовый формат (не JSON)"
            })
    
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Ошибка: {str(e)}"}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "healthy",
        "model": active_model_name
    }), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print(f"Starting server on port {port} with model: {active_model_name}")
    app.run(host='0.0.0.0', port=port, debug=False)
