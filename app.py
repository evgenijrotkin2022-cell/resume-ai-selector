from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import json
import PyPDF2
from docx import Document as DocxDocument
from io import BytesIO
import google.generativeai as genai
from werkzeug.utils import secure_filename
import tempfile

app = Flask(__name__)
CORS(app)  # Разрешаем запросы с Tilda

# Настройка Gemini API (бесплатный)
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

UPLOAD_FOLDER = tempfile.gettempdir()
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(file_path):
    """Извлечение текста из PDF"""
    text = ""
    try:
        with open(file_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
    except Exception as e:
        text = f"Ошибка чтения PDF: {str(e)}"
    return text

def extract_text_from_docx(file_path):
    """Извлечение текста из DOCX"""
    try:
        doc = DocxDocument(file_path)
        text = "\n".join([para.text for para in doc.paragraphs])
        return text
    except Exception as e:
        return f"Ошибка чтения DOCX: {str(e)}"

def analyze_resume_with_ai(resume_text, criteria, candidate_name):
    """Анализ резюме с помощью Gemini AI"""
    try:
        model = genai.GenerativeModel('gemini-pro')
        
        prompt = f"""
Ты эксперт по подбору персонала. Проанализируй резюме кандидата и оцени его по заданным критериям.

КРИТЕРИИ ОТБОРА:
{criteria}

РЕЗЮМЕ КАНДИДАТА ({candidate_name}):
{resume_text[:4000]}

Верни результат СТРОГО в формате JSON (без дополнительного текста):
{{
    "overall_score": <число от 0 до 100>,
    "criteria_scores": {{
        "criterion1": <оценка 0-100>,
        "criterion2": <оценка 0-100>
    }},
    "strengths": ["сильная сторона 1", "сильная сторона 2", "сильная сторона 3"],
    "weaknesses": ["слабая сторона 1", "слабая сторона 2"],
    "reasoning": "Подробное обоснование оценки в 2-3 предложениях",
    "key_highlights": ["ключевой момент 1", "ключевой момент 2"]
}}
"""
        
        response = model.generate_content(prompt)
        result_text = response.text.strip()
        
        # Удаляем markdown форматирование если есть
        if result_text.startswith('```'):
            result_text = result_text.split('```')[1]
            if result_text.startswith('json'):
                result_text = result_text[4:]
        
        result = json.loads(result_text)
        return result
    except Exception as e:
        # Fallback оценка если AI не работает
        return {
            "overall_score": 50,
            "criteria_scores": {},
            "strengths": ["Не удалось проанализировать"],
            "weaknesses": [],
            "reasoning": f"Ошибка анализа: {str(e)}",
            "key_highlights": []
        }

def generate_criteria_automatically(resumes_texts):
    """Автоматическое определение критериев на основе резюме"""
    try:
        model = genai.GenerativeModel('gemini-pro')
        
        combined_text = "\n---\n".join(resumes_texts[:3])  # Берем первые 3 резюме
        
        prompt = f"""
Проанализируй эти резюме и определи 5 ключевых критериев для оценки кандидатов:

{combined_text[:3000]}

Верни только список критериев через запятую, например:
"Опыт работы в области, Технические навыки, Образование, Знание английского языка, Soft skills"
"""
        
        response = model.generate_content(prompt)
        criteria = response.text.strip()
        return criteria
    except:
        return "Опыт работы, Технические навыки, Образование, Коммуникативные навыки, Достижения"

@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "message": "AI Resume Selection API",
        "endpoints": ["/upload", "/health"]
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

@app.route('/upload', methods=['POST'])
def upload_resumes():
    """Основной endpoint для загрузки и анализа резюме"""
    try:
        # Получаем файлы
        if 'files[]' not in request.files:
            return jsonify({"error": "Файлы не загружены"}), 400
        
        files = request.files.getlist('files[]')
        criteria = request.form.get('criteria', '').strip()
        use_auto_criteria = request.form.get('auto_criteria', 'false') == 'true'
        
        if len(files) == 0:
            return jsonify({"error": "Нет файлов для обработки"}), 400
        
        # Парсинг резюме
        resumes = []
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                file.save(filepath)
                
                # Извлечение текста
                if filename.endswith('.pdf'):
                    text = extract_text_from_pdf(filepath)
                elif filename.endswith('.docx') or filename.endswith('.doc'):
                    text = extract_text_from_docx(filepath)
                else:
                    continue
                
                resumes.append({
                    'name': filename,
                    'text': text
                })
                
                # Удаляем временный файл
                os.remove(filepath)
        
        if len(resumes) == 0:
            return jsonify({"error": "Не удалось обработать ни одно резюме"}), 400
        
        # Определение критериев
        if use_auto_criteria or not criteria:
            criteria = generate_criteria_automatically([r['text'] for r in resumes])
        
        # Анализ каждого резюме
        analyzed_resumes = []
        for resume in resumes:
            analysis = analyze_resume_with_ai(resume['text'], criteria, resume['name'])
            analyzed_resumes.append({
                'name': resume['name'],
                'score': analysis['overall_score'],
                'analysis': analysis
            })
        
        # Сортировка и выбор топ-5
        analyzed_resumes.sort(key=lambda x: x['score'], reverse=True)
        top5 = analyzed_resumes[:5]
        
        return jsonify({
            "success": True,
            "criteria": criteria,
            "total_resumes": len(resumes),
            "top5": top5
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/generate-report', methods=['POST'])
def generate_report():
    """Генерация Word отчета с топ-5 кандидатами"""
    try:
        data = request.get_json()
        top5 = data.get('top5', [])
        criteria = data.get('criteria', '')
        
        # Создаем Word документ
        doc = DocxDocument()
        doc.add_heading('Топ-5 кандидатов', 0)
        doc.add_paragraph(f'Критерии отбора: {criteria}')
        doc.add_paragraph('')
        
        for idx, candidate in enumerate(top5, 1):
            doc.add_heading(f'{idx}. {candidate["name"]}', level=1)
            doc.add_paragraph(f'Итоговая оценка: {candidate["score"]}/100')
            
            analysis = candidate.get('analysis', {})
            
            doc.add_heading('Обоснование:', level=2)
            doc.add_paragraph(analysis.get('reasoning', 'Нет данных'))
            
            doc.add_heading('Сильные стороны:', level=2)
            for strength in analysis.get('strengths', []):
                doc.add_paragraph(strength, style='List Bullet')
            
            if analysis.get('key_highlights'):
                doc.add_heading('Ключевые моменты:', level=2)
                for highlight in analysis['key_highlights']:
                    doc.add_paragraph(highlight, style='List Bullet')
            
            doc.add_page_break()
        
        # Сохраняем в BytesIO
        buffer = BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        
        return send_file(
            buffer,
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            as_attachment=True,
            download_name='top5_candidates.docx'
        )
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
