import re
import json

path = r"C:\Users\itsoftware\.gemini\antigravity-ide\brain\59764a25-1ee9-42ce-8ba5-ba539bfcb5bb\.system_generated\steps\450\content.md"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Find all script tags with JSON
scripts = re.findall(r'<script[^>]*>(.*?)</script>', content, re.DOTALL)
print(f"Total script tags: {len(scripts)}")
for i, s in enumerate(scripts):
    s_clean = s.strip()
    if "qatar" in s_clean.lower() or "expiry" in s_clean.lower():
        print(f"Script {i} contains keywords! Length: {len(s_clean)}")
        # print first 500 chars
        print(s_clean[:500])
        print("...")
