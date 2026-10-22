import sys
import os
sys.path.insert(0, os.path.abspath("."))
sys.stdout.reconfigure(encoding="utf-8")
import patient_service

# 1. Routine Query
rep1 = patient_service.handle_patient_query("0918887766", "السلام عليكم، من دكتور العظام اليوم؟")
print("Query 1 Response:")
print(rep1)

# 2. Contextual follow-up
rep2 = patient_service.handle_patient_query("0918887766", "وقداش كشفه؟")
print("\nQuery 2 Response (Contextual Follow-up):")
print(rep2)

# 3. Emergency fast path
rep3 = patient_service.handle_patient_query("0918887766", "أمي عندها ألم حاد ومفاجئ في الصدر وضيق تنفس شديد!")
print("\nQuery 3 Response (Emergency Bypass):")
print(rep3)
assert "تنبيه طبي عاجل" in rep3

print("\nALL PATIENT_SERVICE TESTS PASSED!")
