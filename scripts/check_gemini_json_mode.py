import os, json
from dotenv import load_dotenv
from google import genai
from admin_service import AdminUpdateIntent

load_dotenv()
client = genai.Client(api_key=os.environ.get("GEMINI_KEY"))

prompt = """
أنت مهندس استخراج بيانات. استخرج النية من رسالة مسؤول العيادة:
"دكتور العظام عبدالله روح وما عادش يستقبل اليوم"

أرجع كائن JSON فقط بالصيغة التالية:
{
  "is_valid_update": true,
  "is_ambiguous": false,
  "ambiguity_reason": null,
  "action": "DOCTOR_STATUS_UPDATE",
  "doctor_identifier": "د. يوسف العربي",
  "new_status": "left",
  "daily_note": "أنهى كشوفات اليوم وغادر المصحة",
  "new_price": null,
  "service_identifier": null
}
"""

r = client.models.generate_content(
    model="gemini-3.5-flash",
    contents=prompt,
    config={"response_mime_type": "application/json", "temperature": 0.0}
)
print("RAW RESPONSE:", r.text)
data = json.loads(r.text)
intent = AdminUpdateIntent(**data)
print("VALIDATED INTENT:", intent)
