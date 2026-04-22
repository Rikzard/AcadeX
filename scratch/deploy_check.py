import os
import pytesseract

def test_paths():
    print(f"Current OS: {os.name}")
    
    # Logic from app.py
    if os.name == 'nt':
        tesseract_cmd = r"C:\Tesseract-OCR\tesseract.exe"
        poppler_path = r"C:\poppler\Library\bin"
    else:
        tesseract_cmd = "/usr/bin/tesseract"
        poppler_path = None
        
    print(f"Expected Tesseract Path: {tesseract_cmd}")
    print(f"Expected Poppler Path: {poppler_path}")
    
    # Check if paths exist (if on Windows)
    if os.name == 'nt':
        if os.path.exists(tesseract_cmd):
            print("✅ Tesseract found at Windows path.")
        else:
            print("❌ Tesseract NOT found at Windows path.")
            
        if os.path.exists(poppler_path):
            print("✅ Poppler found at Windows path.")
        else:
            print("❌ Poppler NOT found at Windows path.")

if __name__ == "__main__":
    test_paths()
