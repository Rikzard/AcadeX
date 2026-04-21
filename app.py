"""
AcadeX Backend: AI-Powered Document Analysis
Architected following the standard 8-Step Workflow
Storage: SQLite via Flask-SQLAlchemy (zero-setup, auto-created on first run)
"""

# Fix Windows console encoding before any imports that might log emoji
import os
import sys
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


# ==========================================
# 1. Server Setup & Configuration
# ==========================================
import json
import re
import time
import glob
from datetime import datetime, date, timedelta
from io import BytesIO


from flask import (
    Flask, request, jsonify, render_template,
    send_file, session, redirect, url_for, flash
)
from dotenv import load_dotenv
from functools import wraps

# ── ORM & Security ───────────────────────────────────────────
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

# Initialize Framework & Environment
load_dotenv()

import pytesseract
from PIL import Image
from pdf2image import convert_from_path
import openpyxl

# Local Utilities  (OCR logic kept intact, excel_manager no longer used)
from utils.pyq_analyzer import analyze
from utils.gemini_client import call_gemini_with_retry
from utils import cache_manager

# ==========================================
# App & Database Configuration
# ==========================================
app = Flask(__name__, static_folder='templates/static', static_url_path='/static')
app.secret_key = os.getenv("SECRET_KEY", "super-secret-acadex-key")

# SQLite lives at instance/acadex.db  (Flask default instance path)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///acadex.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ==========================================
# OCR / File Paths (unchanged)
# ==========================================
pytesseract.pytesseract.tesseract_cmd = r"C:\Tesseract-OCR\tesseract.exe"
POPPLER_PATH = r"C:\poppler\Library\bin"

UPLOAD_FOLDER    = "uploads"
SUBMISSIONS_FOLDER = "submissions"
BOOKS_FOLDER     = os.path.join("templates", "static", "books")

os.makedirs(UPLOAD_FOLDER,     exist_ok=True)
os.makedirs(SUBMISSIONS_FOLDER, exist_ok=True)
os.makedirs(BOOKS_FOLDER,      exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


# ==========================================
# 2. ORM Models
# ==========================================

class User(db.Model):
    """Represents a teacher or student account."""
    __tablename__ = "users"

    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80),  unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role          = db.Column(db.String(20),  nullable=False)  # 'teacher' | 'student'

    marks       = db.relationship("Mark",        backref="teacher",    lazy=True)
    activity    = db.relationship("ActivityLog",  backref="actor",     lazy=True,
                                  foreign_keys="ActivityLog.user_id")

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)


class Book(db.Model):
    """A reference book entry, replacing books.json."""
    __tablename__ = "books"

    id       = db.Column(db.Integer,     primary_key=True)
    title    = db.Column(db.String(200), nullable=False)
    author   = db.Column(db.String(200), nullable=False)
    semester = db.Column(db.String(50),  nullable=False)
    subject  = db.Column(db.String(100), nullable=False)
    file_url = db.Column(db.String(400), nullable=False)
    added_at = db.Column(db.DateTime,    default=datetime.utcnow)


class Mark(db.Model):
    """
    Extracted marks record from the Gemini Vision OCR pipeline.
    raw_data stores the full 2-D array (JSON) returned by the AI so
    that variable column structures are preserved without a rigid schema.
    Use raw_data to compute per-subject averages for analytics.
    """
    __tablename__ = "marks"

    id              = db.Column(db.Integer,     primary_key=True)
    teacher_user_id = db.Column(db.Integer,     db.ForeignKey("users.id"), nullable=True)
    source_filename = db.Column(db.String(300))
    subject         = db.Column(db.String(100))
    semester        = db.Column(db.String(50))
    raw_data        = db.Column(db.Text)          # JSON-serialised 2-D list from Gemini
    extracted_at    = db.Column(db.DateTime, default=datetime.utcnow)


class Submission(db.Model):
    """Student mock-test answer submissions, replacing submissions.json."""
    __tablename__ = "submissions"

    id               = db.Column(db.Integer,     primary_key=True)
    student_username = db.Column(db.String(80),  nullable=False)
    semester         = db.Column(db.String(50))
    subject          = db.Column(db.String(100))
    filename         = db.Column(db.String(300))
    submitted_at     = db.Column(db.DateTime, default=datetime.utcnow)


class ActivityLog(db.Model):
    """
    Timestamped event log powering the teacher dashboard "Action Center".
    Written by every meaningful teacher or student action.
    """
    __tablename__ = "activity_log"

    id                 = db.Column(db.Integer,  primary_key=True)
    user_id            = db.Column(db.Integer,  db.ForeignKey("users.id"), nullable=True)
    username           = db.Column(db.String(80))          # denormalised for fast display
    icon               = db.Column(db.String(10), default="📝")
    action_description = db.Column(db.Text)
    timestamp          = db.Column(db.DateTime, default=datetime.utcnow)


# ==========================================
# 3. Database Init & Seeding
# ==========================================

def _seed_default_users() -> None:
    """Insert default teacher and student accounts when the table is empty."""
    if User.query.count() > 0:
        return
    teacher = User(username="teacher_user", role="teacher")
    teacher.set_password("teacher123")
    student = User(username="student_user", role="student")
    student.set_password("student123")
    db.session.add_all([teacher, student])
    db.session.commit()
    print("[AcadeX] Default users seeded: teacher_user / student_user")


def _migrate_books_json() -> None:
    """One-time migration: import legacy books.json → SQLite on first boot."""
    if Book.query.count() > 0:
        return
    books_file = "data/books.json"
    if not os.path.exists(books_file):
        return
    with open(books_file) as f:
        data = json.load(f)
    for semester, subjects in data.items():
        for subject, book_list in subjects.items():
            for b in book_list:
                db.session.add(Book(
                    title=b["title"],
                    author=b["author"],
                    semester=semester,
                    subject=subject,
                    file_url=b.get("url", ""),
                ))
    db.session.commit()
    print("[AcadeX] Migrated books.json -> SQLite")


def _migrate_submissions_json() -> None:
    """One-time migration: import legacy submissions.json → SQLite on first boot."""
    if Submission.query.count() > 0:
        return
    sub_file = "data/submissions.json"
    if not os.path.exists(sub_file):
        return
    with open(sub_file) as f:
        data = json.load(f)
    for entry in data:
        try:
            submitted_at = datetime.strptime(entry["submitted_at"], "%Y-%m-%d %H:%M")
        except Exception:
            submitted_at = datetime.utcnow()
        db.session.add(Submission(
            student_username=entry["student"],
            semester=entry.get("semester", ""),
            subject=entry.get("subject", ""),
            filename=entry.get("filename", ""),
            submitted_at=submitted_at,
        ))
    db.session.commit()
    print("[AcadeX] Migrated submissions.json -> SQLite")


def init_db() -> None:
    """Create all tables, seed users, and run one-time JSON migrations."""
    with app.app_context():
        db.create_all()
        _seed_default_users()
        _migrate_books_json()
        _migrate_submissions_json()


# Run immediately — compatible with both `python app.py` and `flask run`
init_db()


# ==========================================
# Auth Helpers
# ==========================================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


def _log_activity(icon: str, description: str) -> None:
    """Helper: write one ActivityLog entry for the current session user."""
    username = session.get("user", "system")
    user = User.query.filter_by(username=username).first()
    entry = ActivityLog(
        user_id=user.id if user else None,
        username=username,
        icon=icon,
        action_description=description,
        timestamp=datetime.utcnow(),
    )
    db.session.add(entry)
    db.session.commit()


def _humanize_time(dt: datetime) -> str:
    """Return a friendly relative time string for a UTC datetime."""
    if dt is None:
        return ""
    now = datetime.utcnow()
    diff = now - dt
    if diff.days == 0:
        return f"Today, {dt.strftime('%I:%M %p')}"
    elif diff.days == 1:
        return "Yesterday"
    elif diff.days < 7:
        return f"{diff.days} days ago"
    return dt.strftime("%b %d, %Y")


# ==========================================
# Dashboard & Auth Routes
# ==========================================

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/dashboard")
@login_required
def dashboard():
    role     = session.get("role")
    username = session.get("user")

    # ── Teacher Metrics ─────────────────────────────────────────────────────
    if role == "teacher":

        # ① Operational Metrics (live DB queries)
        pending_submissions  = Submission.query.count()
        marks_extracted_today = Mark.query.filter(
            db.func.date(Mark.extracted_at) == date.today()
        ).count()
        pyq_topics_analyzed  = Mark.query.count()      # each extraction = one analysis
        active_reference_books = Book.query.count()

        teacher_metrics = {
            "pending_submissions":   pending_submissions,
            "marks_extracted_today": marks_extracted_today,
            "pyq_topics_analyzed":   pyq_topics_analyzed,
            "active_reference_books": active_reference_books,
        }

        # ② Class Performance per subject (parse Mark.raw_data)
        teacher_class_performance = _compute_class_performance()

        # ③ Top Predicted Topics — still sourced from PYQ cache (file-system)
        #    TODO: replace with real cache_manager or DB query once PYQ results
        #    are stored in the DB.
        teacher_top_topics = [
            {"topic": "Normalization & ACID Properties", "probability": 91},
            {"topic": "Binary Search Trees",             "probability": 85},
            {"topic": "Schrodinger's Wave Equation",     "probability": 79},
            {"topic": "ER Diagrams & Relational Model",  "probability": 76},
            {"topic": "Stack & Queue Implementation",    "probability": 70},
        ]

        # ④ Recent Activity Log (live, last 5 entries)
        raw_events = (
            ActivityLog.query
            .order_by(ActivityLog.timestamp.desc())
            .limit(5)
            .all()
        )
        if raw_events:
            teacher_recent_events = [
                {
                    "icon":  ev.icon,
                    "event": ev.action_description,
                    "time":  _humanize_time(ev.timestamp),
                }
                for ev in raw_events
            ]
        else:
            # No events yet — show a friendly placeholder row
            teacher_recent_events = [
                {"icon": "🚀", "event": "System started — no events recorded yet.", "time": "Just now"},
            ]

        return render_template(
            "index.html",
            role=role,
            teacher_metrics=teacher_metrics,
            teacher_class_performance=teacher_class_performance,
            teacher_top_topics=teacher_top_topics,
            teacher_recent_events=teacher_recent_events,
            # Student context (empty — not rendered for teacher)
            student_metrics={},
            student_recent_books=[],
            student_focus_topics=[],
        )

    # ── Student Metrics ──────────────────────────────────────────────────────
    else:
        student_submission_count = Submission.query.filter_by(
            student_username=username
        ).count()
        # "Pending" = mock tests available (3) minus those already submitted
        pending_assignments = max(0, len(_MOCK_TEST_SUBJECTS) - student_submission_count)

        pdf_notes_extracted = Mark.query.count()   # total OCR runs visible to student

        latest_sub = (
            Submission.query
            .filter_by(student_username=username)
            .order_by(Submission.submitted_at.desc())
            .first()
        )
        latest_grade = latest_sub.subject if latest_sub else "—"

        student_metrics = {
            "pending_assignments":  pending_assignments,
            "mock_test_avg":        "N/A",      # TODO: track scores in a dedicated table
            "pdf_notes_extracted":  pdf_notes_extracted,
            "latest_grade":         latest_grade,
        }

        # Quick Access — 3 most recently added books
        recent_books_raw = Book.query.order_by(Book.added_at.desc()).limit(3).all()
        student_recent_books = [
            {"title": b.title, "author": b.author, "subject": b.subject}
            for b in recent_books_raw
        ]

        # Study Focus Topics (sourced from PYQ cache — same placeholder as teacher)
        # TODO: link to actual cache_manager results saved in DB
        student_focus_topics = [
            "Normalization & ACID Properties",
            "Binary Search Trees & Traversal",
            "Schrodinger's Wave Equation",
            "ER Diagrams & Relational Algebra",
        ]

        return render_template(
            "index.html",
            role=role,
            # Teacher context (empty — not rendered for student)
            teacher_metrics={},
            teacher_class_performance=[],
            teacher_top_topics=[],
            teacher_recent_events=[],
            # Student context
            student_metrics=student_metrics,
            student_recent_books=student_recent_books,
            student_focus_topics=student_focus_topics,
        )


def _compute_class_performance() -> list:
    """
    Parse Mark.raw_data JSON arrays to compute per-subject average scores.
    Looks for columns named 'score', 'marks', 'total', or 'grade'.
    Falls back to a static placeholder list if no marks exist yet.
    """
    marks = Mark.query.all()
    subject_scores: dict = {}

    for mark in marks:
        if not mark.raw_data:
            continue
        try:
            table = json.loads(mark.raw_data)
            if len(table) < 2:
                continue
            headers = [str(h).strip().lower() for h in table[0]]
            score_col = next(
                (i for i, h in enumerate(headers)
                 if any(kw in h for kw in ["score", "marks", "total", "grade"])),
                None,
            )
            if score_col is None:
                continue
            subj = mark.subject or "Unknown"
            for row in table[1:]:
                try:
                    val = float(str(row[score_col]).strip())
                    subject_scores.setdefault(subj, []).append(val)
                except (ValueError, IndexError):
                    pass
        except Exception:
            pass

    if subject_scores:
        return [
            {"subject": s, "avg": round(sum(v) / len(v))}
            for s, v in subject_scores.items()
        ]

    # No marks in DB yet — return a static placeholder
    return [
        {"subject": "DBMS",    "avg": 74},
        {"subject": "DS",      "avg": 68},
        {"subject": "Physics", "avg": 81},
        {"subject": "Maths",   "avg": 59},
        {"subject": "OS",      "avg": 72},
    ]


# ── Mock Test subject list (used for "pending" count calculation) ──────────
_MOCK_TEST_SUBJECTS = ["DBMS", "DS", "Physics Dummy"]


# ==========================================
# 4. Refactored Auth Route
# ==========================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        # ── Query User table instead of hardcoded dict ──────────────────────
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session["user"] = user.username
            session["role"] = user.role
            _log_activity("🔑", f"Logged in as {user.role}")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid credentials. Please try again.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


# ==========================================
# 5. File Ingestion Endpoints (OCR unchanged)
# ==========================================

@app.route("/extract_pdf", methods=["POST"])
@login_required
def extract_pdf():
    file = request.files["file"]
    path = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
    file.save(path)

    images = convert_from_path(path, poppler_path=POPPLER_PATH)
    text = ""
    for img in images:
        text += pytesseract.image_to_string(img)

    if os.path.exists(path):
        os.remove(path)
    return jsonify({"text": text})


@app.route("/extract_image", methods=["POST"])
@login_required
def extract_image():
    if session.get("role") != "teacher":
        return jsonify({"error": "Unauthorized. Teachers only."}), 403

    file = request.files.get("image")
    if not file:
        return jsonify({"error": "No image uploaded"}), 400

    path = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
    file.save(path)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "GEMINI_API_KEY is not set in the .env file."}), 500

    try:
        # 5. AI Prompt Engineering & Execution (unchanged)
        from google import genai
        client  = genai.Client(api_key=api_key)
        myfile  = client.files.upload(file=path)

        prompt = """
        You are an advanced data extraction assistant.
        Your task is to perfectly copy the contents of the main table or grid from the provided image into a structured 2D array.

        Guidelines:
        1. Parse the table EXACTLY as it appears in the image (rows and columns). Keep the headers intact.
        2. Output ONLY a valid JSON List of Lists (a 2D array) representing the table, where the first internal list contains the headers, and the subsequent lists contain the row data.
        3. Do NOT return markdown blocks (like ```json), no conversational text, no explanations, just the raw JSON array.
        Example: [["Header 1", "Header 2"], ["Row 1 Col 1", "Row 1 Col 2"]]
        """

        response = call_gemini_with_retry(prompt, model_name='gemini-2.5-flash', file_obj=myfile)

        # 6. Post-Processing & Validation (unchanged)
        raw_text = response.text
        try:
            json_match = re.search(r'\[.*\]', raw_text, re.DOTALL)
            clean_text = json_match.group(0) if json_match else \
                raw_text.replace("```json", "").replace("```", "").strip()
            table_data = json.loads(clean_text)
        except json.JSONDecodeError:
            print("Failed to parse JSON from Gemini response")
            return jsonify({"error": "Failed to parse JSON from AI", "raw_output": raw_text}), 500

        # 7. Storage Engine — insert Mark record into SQLite (replaces excel_manager)
        teacher_user = User.query.filter_by(username=session["user"]).first()
        mark = Mark(
            teacher_user_id=teacher_user.id if teacher_user else None,
            source_filename=file.filename,
            subject=None,   # TODO: add semester/subject fields to the Tabulator UI
            semester=None,
            raw_data=json.dumps(table_data),
            extracted_at=datetime.utcnow(),
        )
        db.session.add(mark)

        # Log the activity
        _log_activity("🔍", f"Extracted OCR for {file.filename}")

        db.session.commit()

        # 8. Teardown & Response Delivery (Success)
        return jsonify({"success": True, "extracted_data": table_data})

    except Exception as e:
        print(f"Error during API or DB operation: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(path):
            os.remove(path)


@app.route("/download_excel", methods=["GET"])
@login_required
def download_excel():
    """Generate a fresh Excel workbook from all Mark records and stream it."""
    if session.get("role") != "teacher":
        return jsonify({"error": "Unauthorized. Teachers only."}), 403

    marks = Mark.query.order_by(Mark.extracted_at).all()
    if not marks:
        return jsonify({"error": "No marks have been extracted yet."}), 404

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Extracted Marks"

    header_written = False
    for mark in marks:
        if not mark.raw_data:
            continue
        try:
            table = json.loads(mark.raw_data)
            if not header_written and table:
                ws.append(table[0])   # column headers from first extraction
                header_written = True
            for row in table[1:]:
                ws.append(row)
        except Exception:
            pass

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    return send_file(
        buf,
        as_attachment=True,
        download_name="acadex_marks.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ==========================================
# 6. PYQ Analysis Routes (OCR unchanged)
# ==========================================

@app.route("/analyze", methods=["POST"])
@login_required
def analyze_route():
    data     = request.json
    text     = data["text"]
    syllabus = data["syllabus"]
    result   = analyze(text, syllabus)
    return jsonify(result)


@app.route("/analyze_semester", methods=["POST"])
@login_required
def analyze_semester():
    semester = request.form.get("semester")
    subject  = request.form.get("subject")

    if "syllabus" not in request.files:
        return jsonify({"error": "Missing syllabus file"}), 400

    syllabus_file = request.files["syllabus"]

    if not semester or not subject:
        return jsonify({"error": "Missing semester or subject"}), 400

    syllabus_path = os.path.join(app.config["UPLOAD_FOLDER"], f"temp_{syllabus_file.filename}")
    syllabus_file.save(syllabus_path)

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
        if os.path.exists(syllabus_path):
            os.remove(syllabus_path)

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

    cached_analysis = cache_manager.get_cached_analysis(target_dir, pdf_files, syllabus_text)
    if cached_analysis:
        return jsonify(cached_analysis)

    aggregated_text = ""
    for pdf_path in pdf_files:
        try:
            cached_text = cache_manager.get_cached_ocr(pdf_path)
            if cached_text:
                aggregated_text += cached_text + "\n"
                continue
            images = convert_from_path(pdf_path, poppler_path=POPPLER_PATH)
            current_pdf_text = ""
            for img in images:
                current_pdf_text += pytesseract.image_to_string(img) + "\n"
            cache_manager.save_ocr_cache(pdf_path, current_pdf_text)
            aggregated_text += current_pdf_text
        except Exception as e:
            print(f"Error processing {pdf_path}: {e}")

    if not aggregated_text.strip():
        return jsonify({"error": "Failed to extract text from papers."}), 500

    result = analyze(aggregated_text, syllabus_text)

    if result and "error" not in result:
        cache_manager.save_analysis_cache(target_dir, pdf_files, syllabus_text, result)
        # Log successful PYQ analysis
        _log_activity("✅", f"PYQ Analysis complete — {subject}, {semester}")

    return jsonify(result)


# ==========================================
# 7. Books Management (SQLite — replaces books.json)
# ==========================================

@app.route("/api/books", methods=["GET"])
@login_required
def get_books():
    semester = request.args.get("semester")
    subject  = request.args.get("subject")

    books = Book.query.filter_by(semester=semester, subject=subject).all()
    return jsonify([
        {
            "id":     b.id,
            "title":  b.title,
            "author": b.author,
            "url":    b.file_url,
        }
        for b in books
    ])


@app.route("/api/books/add", methods=["POST"])
@login_required
def add_book():
    if session.get("role") != "teacher":
        return jsonify({"error": "Unauthorized"}), 403

    semester  = request.form.get("semester")
    subject   = request.form.get("subject")
    title     = request.form.get("title")
    author    = request.form.get("author")
    book_file = request.files.get("book_file")

    if not all([semester, subject, title, author, book_file]):
        return jsonify({"error": "Missing data or file"}), 400

    # Save physical PDF file (unchanged)
    timestamp  = time.strftime("%Y%m%d_%H%M%S")
    safe_title = re.sub(r'[^a-zA-Z0-9]', '_', title)
    filename   = f"{safe_title}_{timestamp}.pdf"
    filepath   = os.path.join(BOOKS_FOLDER, filename)
    book_file.save(filepath)

    # Insert DB record
    book = Book(
        title=title,
        author=author,
        semester=semester,
        subject=subject,
        file_url=f"/static/books/{filename}",
        added_at=datetime.utcnow(),
    )
    db.session.add(book)
    _log_activity("📚", f"Added book: {title} by {author}")
    db.session.commit()

    return jsonify({"success": True})


@app.route("/api/books/delete", methods=["POST"])
@login_required
def delete_book():
    if session.get("role") != "teacher":
        return jsonify({"error": "Unauthorized"}), 403

    data    = request.json
    book_id = data.get("book_id")

    book = db.session.get(Book, book_id)
    if not book:
        return jsonify({"error": "Book not found"}), 404

    # Delete physical PDF if stored locally
    rel_url = book.file_url
    if rel_url and rel_url.startswith("/static/books/"):
        file_path = os.path.join("templates", "static", "books", os.path.basename(rel_url))
        if os.path.exists(file_path):
            os.remove(file_path)

    _log_activity("🗑️", f"Deleted book: {book.title}")
    db.session.delete(book)
    db.session.commit()
    return jsonify({"success": True})


# ==========================================
# 8. Mock Test (static questions — unchanged)
# ==========================================

MOCK_TESTS = {
    "DBMS": [
        "Explain the 3-tier architecture of DBMS with a neat diagram.",
        "What is normalization? Explain 1NF, 2NF and 3NF with examples.",
        "Differentiate between File System and DBMS.",
        "Explain different types of database users and administrators.",
        "Discuss the concept of ACID properties in transactions.",
    ],
    "DS": [
        "Explain the difference between an Array and a Linked List.",
        "What is a Stack? Implement push and pop operations.",
        "Explain Binary Search Tree (BST) and its traversal methods.",
        "What is Time Complexity? Explain Big O notation.",
        "Discuss different types of Queue data structures.",
    ],
    "Physics Dummy": [
        "What is Schrodinger's wave equation? Derive its time-independent form.",
        "Explain the working of a Ruby Laser with a energy level diagram.",
        "Discuss Heisenberg's Uncertainty Principle.",
        "Explain the properties of superconductors.",
        "What is the photoelectric effect? State Einstein's equation.",
    ],
}


@app.route("/api/static_mock_test", methods=["GET"])
@login_required
def get_static_mock_test():
    subject   = request.args.get("subject")
    questions = MOCK_TESTS.get(subject, [
        f"Question 1 for {subject}: Explain the basic principles.",
        f"Question 2 for {subject}: Discuss the applications of the core concepts.",
        f"Question 3 for {subject}: Draw a detailed diagram for the main architecture.",
        f"Question 4 for {subject}: Differentiate between the primary methods used.",
        f"Question 5 for {subject}: Solve a numerical problem involving the standard formula.",
    ])
    return jsonify(questions)


# ==========================================
# 9. Test Submissions (SQLite — replaces submissions.json)
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

    # Insert DB record (replaces JSON append)
    entry = Submission(
        student_username=student,
        semester=semester,
        subject=subject,
        filename=filename,
        submitted_at=datetime.utcnow(),
    )
    db.session.add(entry)
    _log_activity("📬", f"New submission from {student} ({subject})")
    db.session.commit()

    return jsonify({"success": True})


@app.route("/api/submissions", methods=["GET"])
@login_required
def get_submissions():
    if session.get("role") != "teacher":
        return jsonify({"error": "Unauthorized"}), 403

    rows = Submission.query.order_by(Submission.submitted_at.desc()).all()
    return jsonify([
        {
            "student":      row.student_username,
            "semester":     row.semester,
            "subject":      row.subject,
            "submitted_at": row.submitted_at.strftime("%Y-%m-%d %H:%M"),
            "filename":     row.filename,
        }
        for row in rows
    ])


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