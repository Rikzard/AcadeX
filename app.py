"""
AcadeX Backend: AI-Powered Document Analysis
Architected following the standard 8-Step Workflow
"""

# ==========================================
# 1. Server Setup & Configuration
# ==========================================
import os
import json
import re
import time
import glob
from flask import Flask, request, jsonify, render_template, send_file, session, redirect, url_for, flash
from dotenv import load_dotenv
from functools import wraps

# Initialize Framework & Environment
load_dotenv()

import pytesseract
from PIL import Image
from pdf2image import convert_from_path

# Local Utilities
from utils.pyq_analyzer import analyze
from utils.excel_manager import excel_manager
from utils.gemini_client import call_gemini_with_retry
from utils import cache_manager

app = Flask(__name__, static_folder='templates/static', static_url_path='/static')
app.secret_key = os.getenv("SECRET_KEY", "super-secret-acadex-key")

# Hardcoded Users for Teacher and Student
USERS = {
    "teacher_user": {"password": "teacher123", "role": "teacher"},
    "student_user": {"password": "student123", "role": "student"}
}

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

# Dependencies Setup
pytesseract.pytesseract.tesseract_cmd = r"C:\Tesseract-OCR\tesseract.exe"
POPPLER_PATH = r"C:\poppler\Library\bin"

# Storage Initialization (Create temporary directory on startup)
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Data File Helpers
BOOKS_FILE = "data/books.json"
SUBMISSIONS_FILE = "data/submissions.json"
SUBMISSIONS_FOLDER = "submissions"
os.makedirs(SUBMISSIONS_FOLDER, exist_ok=True)

def load_books():
    if not os.path.exists(BOOKS_FILE):
        return {}
    with open(BOOKS_FILE, "r") as f:
        return json.load(f)

def save_books(data):
    with open(BOOKS_FILE, "w") as f:
        json.dump(data, f, indent=4)

def load_submissions():
    if not os.path.exists(SUBMISSIONS_FILE):
        return []
    with open(SUBMISSIONS_FILE, "r") as f:
        return json.load(f)

def save_submissions(data):
    with open(SUBMISSIONS_FILE, "w") as f:
        json.dump(data, f, indent=4)

@app.route("/")
@login_required
def home():
    return render_template("index.html", role=session.get("role"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        user = USERS.get(username)
        if user and user["password"] == password:
            session["user"] = username
            session["role"] = user["role"]
            return redirect(url_for("home"))
        else:
            flash("Invalid credentials. Please try again.", "error")
            
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ==========================================
# 2. File Ingestion (The Endpoints)
# ==========================================

@app.route("/extract_pdf", methods=["POST"])
@login_required
def extract_pdf():
    # Receive & Store temporarily
    file = request.files["file"]
    path = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
    file.save(path)

    # 3. OCR Pipeline (Pre-processing)
    images = convert_from_path(path, poppler_path=POPPLER_PATH)
    text = ""
    for img in images:
        text += pytesseract.image_to_string(img)

    # 8. Teardown & Response Delivery
    if os.path.exists(path):
        os.remove(path)
    return jsonify({"text": text})


@app.route("/extract_image", methods=["POST"])
@login_required
def extract_image():
    if session.get("role") != "teacher":
        return jsonify({"error": "Unauthorized. Teachers only."}), 403
    # Receive & Store temporarily
    file = request.files.get("image")
    if not file:
        return jsonify({"error": "No image uploaded"}), 400

    path = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
    file.save(path)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "GEMINI_API_KEY is not set in the .env file."}), 500

    try:
        # 5. AI Prompt Engineering & Execution
        from google import genai
        client = genai.Client(api_key=api_key)
        myfile = client.files.upload(file=path)
        
        prompt = """
        You are an advanced data extraction assistant.
        Your task is to perfectly copy the contents of the main table or grid from the provided image into a structured 2D array.
        
        Guidelines:
        1. Parse the table EXACTLY as it appears in the image (rows and columns). Keep the headers intact.
        2. Output ONLY a valid JSON List of Lists (a 2D array) representing the table, where the first internal list contains the headers, and the subsequent lists contain the row data.
        3. Do NOT return markdown blocks (like ```json), no conversational text, no explanations, just the raw JSON array.
        Example: [["Header 1", "Header 2"], ["Row 1 Col 1", "Row 1 Col 2"]]
        """
        
        # Use centralized utility with retry and text limiting
        response = call_gemini_with_retry(prompt, model_name='gemini-2.5-flash', file_obj=myfile)

        # 6. Post-Processing & Validation
        raw_text = response.text
        try:
            # Clean the Output & Parse Data
            json_match = re.search(r'\[.*\]', re.DOTALL)
            if json_match:
                clean_text = json_match.group(0)
            else:
                clean_text = raw_text.replace("```json", "").replace("```", "").strip()
                
            table_data = json.loads(clean_text)
        except json.JSONDecodeError:
            print("Failed to parse JSON")
            return jsonify({"error": "Failed to parse JSON from AI", "raw_output": response.text}), 500

        # 7. Storage Engine
        excel_manager.append_data(file.filename, table_data)

        # 8. Teardown & Response Delivery (Success)
        return jsonify({"success": True, "extracted_data": table_data})

    except Exception as e:
        print(f"Error during API or Excel operation: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        # 8. Teardown (Cleanup)
        if os.path.exists(path):
            os.remove(path)

# Download Active Excel Sheet (Storage output routing)
@app.route("/download_excel", methods=["GET"])
@login_required
def download_excel():
    if session.get("role") != "teacher":
        return jsonify({"error": "Unauthorized. Teachers only."}), 403
    excel_path = os.path.abspath("data/student_marks.xlsx")
    if os.path.exists(excel_path):
        return send_file(excel_path, as_attachment=True)
    return jsonify({"error": "No marks have been scanned yet."}), 404


@app.route("/analyze", methods=["POST"])
@login_required
def analyze_route():
    data = request.json
    text = data["text"]
    syllabus = data["syllabus"]
    
    # 5 & 6 handled entirely inside utils.pyq_analyzer
    result = analyze(text, syllabus)
    return jsonify(result)


@app.route("/analyze_semester", methods=["POST"])
@login_required
def analyze_semester():
    # Receive Metadata
    semester = request.form.get("semester")
    subject = request.form.get("subject")
    
    if "syllabus" not in request.files:
        return jsonify({"error": "Missing syllabus file"}), 400
    
    syllabus_file = request.files["syllabus"]
    
    if not semester or not subject:
        return jsonify({"error": "Missing semester or subject"}), 400

    # Receive & Store syllabus temporarily
    syllabus_path = os.path.join(app.config["UPLOAD_FOLDER"], f"temp_{syllabus_file.filename}")
    syllabus_file.save(syllabus_path)
    
    # 3. OCR Pipeline (Syllabus)
    syllabus_text = ""
    try:
        if syllabus_path.lower().endswith('.pdf'):
            syl_images = convert_from_path(syllabus_path, poppler_path=POPPLER_PATH)
            for img in syl_images:
                syllabus_text += pytesseract.image_to_string(img) + "\n"
        else:
            syl_img = Image.open(syllabus_path)
            syllabus_text += pytesseract.image_to_string(syl_img)
    except Exception as e:
        print(f"Error processing syllabus: {e}")
        return jsonify({"error": "Failed to parse syllabus file."}), 500
    finally:
        # 8. Teardown (Syllabus Cleanup)
        if os.path.exists(syllabus_path):
            os.remove(syllabus_path)
            
    # 4. Data Aggregation (Combine multiple PDFs from the system directory)
    target_dir = os.path.join(app.config["UPLOAD_FOLDER"], semester, subject.strip().lower())
    
    if not os.path.isdir(target_dir):
        alt_target = os.path.join(app.config["UPLOAD_FOLDER"], semester, subject.strip())
        if os.path.isdir(alt_target):
            target_dir = alt_target
        else:
            return jsonify({"error": f"Folder for {subject} not found in {semester}."}), 404

    pdf_files = glob.glob(os.path.join(target_dir, "*.pdf"))

    if not pdf_files:
        return jsonify({"error": f"No question papers found for {subject} in {semester}."}), 404

    # NEW: Check for full Analysis Cache hit
    cached_analysis = cache_manager.get_cached_analysis(target_dir, pdf_files, syllabus_text)
    if cached_analysis:
        return jsonify(cached_analysis)

    aggregated_text = ""
    for pdf_path in pdf_files:
        try:
            # NEW: Check for individual OCR Cache hit
            cached_text = cache_manager.get_cached_ocr(pdf_path)
            if cached_text:
                aggregated_text += cached_text + "\n"
                continue

            # 3. OCR Pipeline (Target Data) - Cache Miss
            images = convert_from_path(pdf_path, poppler_path=POPPLER_PATH)
            current_pdf_text = ""
            for img in images:
                current_pdf_text += pytesseract.image_to_string(img) + "\n"
            
            # Save to OCR Cache
            cache_manager.save_ocr_cache(pdf_path, current_pdf_text)
            aggregated_text += current_pdf_text
        except Exception as e:
            print(f"Error processing {pdf_path}: {e}")

    if not aggregated_text.strip():
        return jsonify({"error": "Failed to extract text from papers."}), 500

    # 5, 6, & 8. API Execution, Validation, and Response
    result = analyze(aggregated_text, syllabus_text)
    
    # Save to Analysis Cache (if successful)
    if result and "error" not in result:
        cache_manager.save_analysis_cache(target_dir, pdf_files, syllabus_text, result)
        
    return jsonify(result)


# ==========================================
# Books Management Endpoints
# ==========================================

@app.route("/api/books", methods=["GET"])
@login_required
def get_books():
    semester = request.args.get("semester")
    subject = request.args.get("subject")
    
    books = load_books()
    sem_books = books.get(semester, {})
    sub_books = sem_books.get(subject, [])
    
    return jsonify(sub_books)

@app.route("/api/books/add", methods=["POST"])
@login_required
def add_book():
    if session.get("role") != "teacher":
        return jsonify({"error": "Unauthorized"}), 403
        
    data = request.json
    semester = data.get("semester")
    subject = data.get("subject")
    title = data.get("title")
    author = data.get("author")
    
    if not all([semester, subject, title, author]):
        return jsonify({"error": "Missing data"}), 400
        
    books = load_books()
    if semester not in books:
        books[semester] = {}
    if subject not in books[semester]:
        books[semester][subject] = []
        
    books[semester][subject].append({
        "title": title, 
        "author": author,
        "url": "/static/sample_book.pdf"
    })
    save_books(books)
    
    return jsonify({"success": True})

@app.route("/api/books/delete", methods=["POST"])
@login_required
def delete_book():
    if session.get("role") != "teacher":
        return jsonify({"error": "Unauthorized"}), 403
        
    data = request.json
    semester = data.get("semester")
    subject = data.get("subject")
    index = data.get("index")
    
    books = load_books()
    try:
        if semester in books and subject in books[semester]:
            books[semester][subject].pop(int(index))
            save_books(books)
            return jsonify({"success": True})
    except (IndexError, ValueError):
        pass
        
    return jsonify({"error": "Failed to delete"}), 400


# ==========================================
# Mock Test Persistence & Static Data
# ==========================================

MOCK_TESTS = {
    "DBMS": [
        "Explain the 3-tier architecture of DBMS with a neat diagram.",
        "What is normalization? Explain 1NF, 2NF and 3NF with examples.",
        "Differentiate between File System and DBMS.",
        "Explain different types of database users and administrators.",
        "Discuss the concept of ACID properties in transactions."
    ],
    "DS": [
        "Explain the difference between an Array and a Linked List.",
        "What is a Stack? Implement push and pop operations.",
        "Explain Binary Search Tree (BST) and its traversal methods.",
        "What is Time Complexity? Explain Big O notation.",
        "Discuss different types of Queue data structures."
    ],
    "Physics Dummy": [
        "What is Schrodinger's wave equation? Derive its time-independent form.",
        "Explain the working of a Ruby Laser with a energy level diagram.",
        "Discuss Heisenberg's Uncertainty Principle.",
        "Explain the properties of superconductors.",
        "What is the photoelectric effect? State Einstein's equation."
    ]
}

@app.route("/api/static_mock_test", methods=["GET"])
@login_required
def get_static_mock_test():
    subject = request.args.get("subject")
    
    # Return specific mock test if exists, else generic questions
    questions = MOCK_TESTS.get(subject, [
        f"Question 1 for {subject}: Explain the basic principles.",
        f"Question 2 for {subject}: Discuss the applications of the core concepts.",
        f"Question 3 for {subject}: Draw a detailed diagram for the main architecture.",
        f"Question 4 for {subject}: Differentiate between the primary methods used.",
        f"Question 5 for {subject}: Solve a numerical problem involving the standard formula."
    ])
    
    return jsonify(questions)


# ==========================================
# Test Submissions Endpoints
# ==========================================

@app.route("/api/submit_test", methods=["POST"])
@login_required
def submit_test():
    if session.get("role") != "student":
        return jsonify({"error": "Only students can submit tests."}), 403

    semester = request.form.get("semester")
    subject  = request.form.get("subject")
    ans_file = request.files.get("answer_file")

    if not ans_file or not semester or not subject:
        return jsonify({"error": "Missing data or file."}), 400

    student   = session["user"]
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    safe_sub  = subject.replace(" ", "_")
    filename  = f"{student}_{safe_sub}_{timestamp}{os.path.splitext(ans_file.filename)[1]}"
    filepath  = os.path.join(SUBMISSIONS_FOLDER, filename)
    ans_file.save(filepath)

    entry = {
        "student":      student,
        "semester":     semester,
        "subject":      subject,
        "submitted_at": time.strftime("%Y-%m-%d %H:%M"),
        "filename":     filename
    }
    submissions = load_submissions()
    submissions.append(entry)
    save_submissions(submissions)

    return jsonify({"success": True})


@app.route("/api/submissions", methods=["GET"])
@login_required
def get_submissions():
    if session.get("role") != "teacher":
        return jsonify({"error": "Unauthorized"}), 403
    return jsonify(load_submissions())


@app.route("/api/submissions/download/<filename>", methods=["GET"])
@login_required
def download_submission(filename):
    if session.get("role") != "teacher":
        return jsonify({"error": "Unauthorized"}), 403
    filepath = os.path.join(SUBMISSIONS_FOLDER, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    return send_file(os.path.abspath(filepath), as_attachment=True)


# ==========================================
# Run app
# ==========================================
if __name__ == "__main__":
    app.run(debug=True)