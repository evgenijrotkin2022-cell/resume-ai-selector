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

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', 'AIzaSyBrblYdHmCrrxLu3atlu1uhxvUvj8e9buM')
genai.configure(api_key=GEMINI_API_KEY)

generation_config = {
    "temperature": 0.7,
    "top_p": 0.95,
    "top_k": 64,
    "max_output_tokens": 8192,
}

model = genai.GenerativeModel(
    model_name='gemini-1.5-flash',
    generation_config=generation_config,
)

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
        "version": "4.0",
        "model": "gemini-1.5-flash"
    })

@app.route('/analyze', methods=['POST'])
def analyze_resumes():
    try:
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
                    "text": text[:6000]
                })
                print(f"Processed file {idx + 1}: {filename} ({len(text)} chars)")
        
        if not resumes_data:
            return jsonify({"error": "Не удалось извлечь текст из файлов"}), 400
        
        prompt = f"""Ты - эксперт HR. Проанализируй резюме и выбери ТОП-5 лучших кандидатов.

КРИТЕРИИ: {criteria if criteria else "Общая квалификация, опыт, образование, навыки"}

РЕЗЮМЕ:
"""
        
        for resume in resumes_data:
            prompt += f"\n[РЕЗЮМЕ {resume['id']}] Файл: {resume['filename']}\n{resume['text']}\n---\n"
        
        prompt += """
Ответь ТОЛЬКО в формате JSON (без markdown):
{
  "top_candidates": [
    {
      "rank": 1,
      "resume_id": 1,
      "filename": "имя_файла",
      "score": 95,
      "strengths": ["сильная сторона 1", "сильная сторона 2", "сильная сторона 3"],
      "reasons": "Почему этот кандидат лучший (2-3 предложения)",
      "key_skills": ["навык1", "навык2", "навык3"]
    }
  ],
  "summary": "Краткое резюме по всем топ кандидатам"
}
"""
        
        print("Sending request to Gemini API...")
        
        try:
            response = model.generate_content(prompt)
            result_text = response.text
            print(f"Received response: {len(result_text)} chars")
        except Exception as api_error:
            print(f"Gemini API error: {str(api_error)}")
            return jsonify({"error": f"Ошибка Gemini API: {str(api_error)}"}), 500
        
        result_text = result_text.strip()
        if result_text.startswith('```json'):
            result_text = result_text[7:]
        elif result_text.startswith('```'):
            result_text = result_text[3:]
        if result_text.endswith('```'):
            result_text = result_text[:-3]
        result_text = result_text.strip()
        
        try:
            result = json.loads(result_text)
            if 'top_candidates' in result and len(result['top_candidates']) > 5:
                result['top_candidates'] = result['top_candidates'][:5]
            print(f"Success! Found {len(result.get('top_candidates', []))} candidates")
            return jsonify(result)
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            return jsonify({
                "raw_response": result_text,
                "note": "Ответ в текстовом формате"
            })
    
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Ошибка сервера: {str(e)}"}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "model": "gemini-1.5-flash"}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print(f"Starting server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
