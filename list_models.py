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

try:
    models = list(client.models.list())
    print("Available models:")
    for m in models:
        if "gemini" in m.name:
            print(f"- {m.name}")
except Exception as e:
    print(f"Error listing models: {e}")
