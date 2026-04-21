import os
import time
import logging
from google import genai
from google.genai import errors

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def call_gemini_with_retry(prompt, model_name='gemini-2.5-flash', max_retries=7, text_limit=30000, file_obj=None):
    """
    Calls the Gemini API with robust exponential backoff retry logic and text limiting.
    
    Args:
        prompt (str): The text prompt or content to send.
        model_name (str): The Gemini model to use.
        max_retries (int): Maximum number of retry attempts.
        text_limit (int): Maximum character limit for the prompt text.
        file_obj (Optional): A file object uploaded via client.files.upload()
        
    Returns:
        The API response object.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is missing from environment.")

    client = genai.Client(api_key=api_key)

    # Limit text size if prompt is a string
    if isinstance(prompt, str) and len(prompt) > text_limit:
        logger.warning(f"Prompt text is too large ({len(prompt)} chars). Truncating to {text_limit} chars.")
        prompt = prompt[:text_limit] + "\n... [TRUNCATED DUE TO SIZE]"

    # Prepare contents
    contents = [prompt]
    if file_obj:
        contents = [file_obj, prompt]

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents
            )
            return response
        except Exception as e:
            error_str = str(e).upper()
            # 503 (Unavailable), 429 (Rate Limit), and general transient networking/overload errors
            is_transient = any(msg in error_str for msg in ["503", "429", "UNAVAILABLE", "OVERLOADED", "DEADLINE_EXCEEDED", "INTERNAL"])
            
            if is_transient and attempt < max_retries - 1:
                # Use a slightly more patient backoff: 3, 6, 12, 24... seconds
                wait_time = 3 * (2 ** attempt)
                logger.warning(f"[Gemini] Busy/overloaded (Attempt {attempt + 1}/{max_retries}). Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                logger.error(f"[Gemini] API call failed after {attempt + 1} attempts: {e}")
                raise e

    raise Exception("API failed after maximum retries")
