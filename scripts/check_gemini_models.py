import sys
import os
from dotenv import load_dotenv

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

from google import genai

client = genai.Client(api_key=api_key)

candidates = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash"]

for m in candidates:
    try:
        print(f"Trying model: {m}...")
        resp = client.models.generate_content(
            model=m,
            contents="مرحبا، أجب بكلمة واحدة: نعم"
        )
        print(f"SUCCESS with {m}! Response: {resp.text.strip()}")
        # Save working model to .env
        with open(".env", "r", encoding="utf-8") as f:
            content = f.read()
        import re
        content = re.sub(r"GEMINI_MODEL=.*", f"GEMINI_MODEL={m}", content)
        with open(".env", "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Updated .env with GEMINI_MODEL={m}")
        break
    except Exception as e:
        print(f"Error with {m}: {e}")
