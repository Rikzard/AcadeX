from flask import Flask, request, jsonify, render_template
import os
import pytesseract
from PIL import Image
from pdf2image import convert_from_path
from utils.pyq_analyzer import analyze

# Set Tesseract path
pytesseract.pytesseract.tesseract_cmd = r"C:\Tesseract-OCR\tesseract.exe"

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


@app.route("/")
def home():
    return render_template("index.html")


# -----------------------------
# Extract text from PDF
# -----------------------------
@app.route("/extract_pdf", methods=["POST"])
def extract_pdf():
    file = request.files["file"]
    path = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
    file.save(path)

    images = convert_from_path(
        path,
        poppler_path=r"C:\poppler\Library\bin"
    )

    text = ""
    for img in images:
        text += pytesseract.image_to_string(img)

    return jsonify({"text": text})


from dotenv import load_dotenv
load_dotenv()

from utils.excel_manager import excel_manager
import json
from flask import send_file

# -----------------------------
# Extract Marks from Answer Sheet
# -----------------------------
@app.route("/extract_image", methods=["POST"])
def extract_image():
    file = request.files.get("image")
    if not file:
        return jsonify({"error": "No image uploaded"}), 400

    path = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
    file.save(path)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "GEMINI_API_KEY is not set in the .env file."}), 500

    try:
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
        
        import time
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=[myfile, prompt],
                )
                break
            except Exception as e:
                if ("503" in str(e) or "429" in str(e) or "UNAVAILABLE" in str(e).upper()) and attempt < max_retries - 1:
                    print(f"API busy (attempt {attempt + 1}), retrying in {2 ** attempt} seconds...")
                    time.sleep(2 ** attempt)
                else:
                    raise e

        # Parse JSON robustly
        import re
        raw_text = response.text
        
        try:
            # Extract JSON array using regex if there's surrounding text
            json_match = re.search(r'\[.*\]', raw_text, re.DOTALL)
            if json_match:
                clean_text = json_match.group(0)
            else:
                clean_text = raw_text.replace("```json", "").replace("```", "").strip()
                
            table_data = json.loads(clean_text)
        except json.JSONDecodeError:
            print("Failed to parse JSON")
            print("Raw Output from Gemini:", response.text)
            return jsonify({"error": "Failed to parse JSON from AI", "raw_output": response.text}), 500

        # Build Excel Database
        excel_manager.append_data(file.filename, table_data)

        return jsonify({"success": True, "extracted_data": table_data})

    except Exception as e:
        print(f"Error during API or Excel operation: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(path):
            os.remove(path)


# -----------------------------
# Download Active Excel Sheet
# -----------------------------
@app.route("/download_excel", methods=["GET"])
def download_excel():
    excel_path = os.path.abspath("data/student_marks.xlsx")
    if os.path.exists(excel_path):
        return send_file(excel_path, as_attachment=True)
    return jsonify({"error": "No marks have been scanned yet."}), 404

# -----------------------------
# Analyze text
# -----------------------------
@app.route("/analyze", methods=["POST"])
def analyze_route():
    data = request.json

    text = data["text"]
    syllabus = data["syllabus"]

    result = analyze(text, syllabus)

    return jsonify(result)

# -----------------------------
# Analyze by Semester and Subject
# -----------------------------
@app.route("/analyze_semester", methods=["POST"])
def analyze_semester():
    import glob
    semester = request.form.get("semester")
    subject = request.form.get("subject")
    
    if "syllabus" not in request.files:
        return jsonify({"error": "Missing syllabus file"}), 400
    
    syllabus_file = request.files["syllabus"]
    
    if not semester or not subject:
        return jsonify({"error": "Missing semester or subject"}), 400

    # Parse the uploaded Syllabus File via OCR to get syllabus text
    syllabus_path = os.path.join(app.config["UPLOAD_FOLDER"], f"temp_{syllabus_file.filename}")
    syllabus_file.save(syllabus_path)
    
    syllabus_text = ""
    try:
        if syllabus_path.lower().endswith('.pdf'):
            syl_images = convert_from_path(syllabus_path, poppler_path=r"C:\poppler\Library\bin")
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
        # Fallback raw check for folder lookup
        alt_target = os.path.join(app.config["UPLOAD_FOLDER"], semester, subject.strip())
        if os.path.isdir(alt_target):
            target_dir = alt_target
        else:
            return jsonify({"error": f"Folder for {subject} not found in {semester}."}), 404

    pdf_files = glob.glob(os.path.join(target_dir, "*.pdf"))

    if not pdf_files:
        return jsonify({"error": f"No question papers found for {subject} in {semester}."}), 404

    aggregated_text = ""

    for pdf_path in pdf_files:
        try:
            images = convert_from_path(
                pdf_path,
                poppler_path=r"C:\poppler\Library\bin"
            )
            for img in images:
                aggregated_text += pytesseract.image_to_string(img) + "\n"
        except Exception as e:
            print(f"Error processing {pdf_path}: {e}")

    if not aggregated_text.strip():
        return jsonify({"error": "Failed to extract text from papers."}), 500

    result = analyze(aggregated_text, syllabus_text)
    return jsonify(result)


# -----------------------------
# Run app (ALWAYS LAST)
# -----------------------------
if __name__ == "__main__":
    app.run(debug=True)