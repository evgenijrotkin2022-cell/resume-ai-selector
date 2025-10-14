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
model = genai.GenerativeModel('gemini-pro')

def extract_text_from_pdf(file_content):
    """Извлекает текст из PDF"""
    try:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_content))
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text()
        return text
    except:
        return ""

def extract_text_from_docx(file_content):
    """Извлекает текст из DOCX"""
    try:
        doc = docx.Document(io.BytesIO(file_content))
        text = "\n".join([para.text for para in doc.paragraphs])
        return text
    except:
        return ""

@app.route('/')
def home():
    return jsonify({
        "status": "ok",
        "message": "Resume Analyzer API работает!"
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
            if filename.lower().endswith('.pdf'):
                text = extract_text_from_pdf(file_content)
            elif filename.lower().endswith('.docx'):
                text = extract_text_from_docx(file_content)
            elif filename.lower().endswith('.txt'):
                text = file_content.decode('utf-8', errors='ignore')
            else:
                text = ""
            
            if text:
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

Ответь в формате JSON:
{
  "top_candidates": [
    {
      "rank": 1,
      "resume_id": номер резюме,
      "filename": "имя файла",
      "score": оценка от 1 до 100,
      "strengths": ["сильная сторона 1", "сильная сторона 2", "..."],
      "reasons": "Почему этот кандидат в топ-5 (2-3 предложения)",
      "key_skills": ["навык 1", "навык 2", "..."]
    }
  ],
  "summary": "Общее резюме по топ-5 кандидатам"
}

Верни ТОЛЬКО JSON, без дополнительного текста.
"""
        
        # Отправляем запрос в Gemini
        response = model.generate_content(prompt)
        result_text = response.text
        
        # Очищаем ответ от markdown
        result_text = result_text.replace('```json', '').replace('```', '').strip()
        
        try:
            result = json.loads(result_text)
        except:
            # Если не удалось распарсить JSON, возвращаем как текст
            result = {
                "raw_response": result_text,
                "note": "Ответ в текстовом формате"
            }
        
        return jsonify(result)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
```

**Файл 2: `requirements.txt`** (зависимости Python)
```
flask==3.0.0
flask-cors==4.0.0
google-generativeai==0.3.2
PyPDF2==3.0.1
python-docx==1.1.0
gunicorn==21.2.0
