import os
from typing import Optional
from app.config import settings

def transcribe_audio_bytes(audio_bytes: bytes, mime_type: str = "audio/ogg") -> Optional[str]:
    """Transcribes voice notes using Gemini Flash multimodal capabilities."""
    if not (settings.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY")):
        return "عذراً، خدمة تحويل الصوت إلى نص تتطلب تهيئة مفتاح GEMINI_API_KEY."

    try:
        from google import genai
        from google.genai import types

        api_key = settings.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY")
        client = genai.Client(api_key=api_key)

        prompt = "قم بتفريغ هذه الرسالة الصوتية الطبية/العامة إلى نص عربي دقيق جداً كلمة بكلمة، مع مراعاة اللهجة العربية المحكية بدقة دون أي تعليق إضافي منك سوى النص المنطوق."

        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(
                    data=audio_bytes,
                    mime_type=mime_type,
                ),
                prompt
            ]
        )
        return response.text.strip()
    except Exception as e:
        print(f"Error transcribing audio: {e}")
        return None
