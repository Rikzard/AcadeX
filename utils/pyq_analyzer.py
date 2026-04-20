import os
import json
import re

def analyze(text, syllabus):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {"error": "GEMINI_API_KEY is missing from environment. Please set it."}
        
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        
        prompt = """
        You are an intelligent Academic Analyzer. 
        You are given the Syllabus and raw OCR text from past Question Papers.
        
        Your tasks:
        1. Identify questions from the Question Papers text.
        2. Group semantically identical questions (even if worded differently or containing OCR typos) into a single representative question.
        3. Count their frequencies (how many times they were repeated across the papers).
        4. Match each question to the best relevant topic present in the Syllabus.
        
        Return ONLY a raw JSON object in this EXACT format (no markdown blocks ```json, no extra text):
        {
          "top_questions": [
            {
              "question": "Representative Question Form",
              "topic": "Matching Syllabus Topic",
              "frequency": 3
            }
          ]
        }
        """
        
        contents = f"SYLLABUS:\n{syllabus}\n\nQUESTION PAPERS:\n{text}\n\n{prompt}"
        
        import time
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=contents,
                )
                break
            except Exception as e:
                if ("503" in str(e) or "429" in str(e) or "UNAVAILABLE" in str(e).upper()) and attempt < max_retries - 1:
                    print(f"API busy (attempt {attempt + 1}), retrying in {2 ** attempt} seconds...")
                    time.sleep(2 ** attempt)
                else:
                    raise e
        
        raw_text = response.text
        
        # Robust JSON Parsing
        try:
            json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
            if json_match:
                clean_text = json_match.group(0)
            else:
                clean_text = raw_text.replace("```json", "").replace("```", "").strip()
                
            data = json.loads(clean_text)
            
            # Sort deeply by frequency to show most repeated questions first
            if "top_questions" in data:
                 data["top_questions"] = sorted(data["top_questions"], key=lambda x: x.get("frequency", 0), reverse=True)
                 
            return data
        except json.JSONDecodeError:
            print("Failed to parse JSON")
            print("Raw Output from Gemini:", response.text)
            return {"error": "Failed to parse JSON from AI"}
            
    except Exception as e:
        print(f"Error during Gemini PyQ Analysis: {e}")
        return {"error": str(e)}