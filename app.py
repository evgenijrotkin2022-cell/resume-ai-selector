from flask import Flask, request, jsonify
from flask_cors import CORS
import google.generativeai as genai
import PyPDF2
import docx
import io
import os
import json

app = Flask(__name__)
CORS(app)

# Настройка Gemini API
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', 'AIzaSyBrblYdHmCrrxLu3atlu1uhxvUvj8e9buM')
genai.configure(api_key=GEMINI_API_KEY)

# ИСПРАВЛЕНО: Используем новое название модели
model = genai.GenerativeModel('gemini-1.5-flash')

def extract_text_from_pdf(file_content):
    """Извлекает текст из PDF"""
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
    """Извлекает текст из DOCX"""
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
        "version": "2.0"
    })

@app.route('/analyze', methods=['POST'])
def analyze_resumes():
    try:
        files = request.files.getlist('resumes')
        criteria = request.form.get('criteria', '')
        
        if not files:
            return jsonify({"error": "Файлы не загружены"}), 400
        
        # Извлекаем текст из всех резюме
        resumes_data = []
        for idx, file in enumerate(files):
            filename = file.filename
            file_content = file.read()
            
            # Определяем тип файла и извлекаем текст
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
                    "text": text[:8000]  # Ограничиваем длину
                })
        
        if not resumes_data:
            return jsonify({"error": "Не удалось извлечь текст из файлов"}), 400
        
        # Формируем промт для Gemini
        prompt = f"""
Ты - эксперт по подбору персонала. Проанализируй следующие резюме и выбери ТОП-5 лучших кандидатов.

Критерии отбора: {criteria if criteria else "Общая квалификация, опыт работы, образование, навыки"}

Резюме:
"""
        
        for resume in resumes_data:
            prompt += f"\n\n--- РЕЗЮМЕ #{resume['id']} (Файл: {resume['filename']}) ---\n{resume['text']}\n"
        
        prompt += """

Ответь СТРОГО в формате JSON (без markdown, без комментариев):
{
  "top_candidates": [
    {
      "rank": 1,
      "resume_id": 1,
      "filename": "имя файла",
      "score": 95,
      "strengths": ["сильная сторона 1", "сильная сторона 2"],
      "reasons": "Краткое объяснение почему этот кандидат в топе",
      "key_skills": ["навык 1", "навык 2"]
    }
  ],
  "summary": "Общее резюме по топ кандидатам"
}

Верни ТОЛЬКО валидный JSON, ничего больше.
"""
        
        # Отправляем запрос в Gemini
        print(f"Sending request to Gemini with {len(resumes_data)} resumes")
        response = model.generate_content(prompt)
        result_text = response.text
        
        print(f"Gemini response: {result_text[:200]}...")
        
        # Очищаем ответ от markdown
        result_text = result_text.strip()
        if result_text.startswith('```json'):
            result_text = result_text[7:]
        if result_text.startswith('```'):
            result_text = result_text[3:]
        if result_text.endswith('```'):
            result_text = result_text[:-3]
        result_text = result_text.strip()
        
        try:
            result = json.loads(result_text)
            # Ограничиваем до топ-5
            if 'top_candidates' in result and len(result['top_candidates']) > 5:
                result['top_candidates'] = result['top_candidates'][:5]
            return jsonify(result)
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            print(f"Raw response: {result_text}")
            # Возвращаем как текст, если не удалось распарсить
            return jsonify({
                "raw_response": result_text,
                "note": "Ответ в текстовом формате (не удалось распарсить JSON)"
            })
    
    except Exception as e:
        print(f"Error in analyze_resumes: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
