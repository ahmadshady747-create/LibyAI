import sys
import os
sys.path.insert(0, os.path.abspath("."))
sys.stdout.reconfigure(encoding="utf-8")
from triage import normalize_arabic, evaluate_triage, COMPILED_RED_FLAGS

t = "أمي عندها ألم حاد ومفاجئ في الصدر وضيق تنفس شديد!"
norm = normalize_arabic(t)
print("Norm:", norm)
res = evaluate_triage(t)
print("Triage:", res.level, res.is_emergency)
for cat, patterns in COMPILED_RED_FLAGS.items():
    for p in patterns:
        m = p.search(norm)
        if m:
            print("Matched:", cat, p.pattern)
