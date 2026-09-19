from __future__ import annotations
import json
import re
from pathlib import Path
import requests

FOLDER_ID = "14oA8BJi-MBQ7SYCl3rQZX-LkWgGwUI9j"
URL = f"https://drive.google.com/drive/folders/{FOLDER_ID}?usp=sharing"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
out = Path(r"C:\Users\Administrator\Downloads\3D-Printing-Social-Automation\scripts\_drive_probe.html")

r = requests.get(URL, headers=HEADERS, timeout=60)
t = r.text
out.write_text(t, encoding="utf-8")
print("status", r.status_code, "len", len(t), "saved", out)

checks = [
    "_DRIVE_ivd",
    "folderViewer",
    "viewerItems",
    "itemName",
    "application/vnd",
    "This folder",
    "You need access",
    "Request access",
    "docs-homesview",
    "AF_initDataCallback",
    "KEY_FOLDER",
]
for p in checks:
    print(p, t.find(p))

exts = re.findall(r"([A-Za-z0-9 _\-\(\)\.]{3,120}\.(?:pdf|xlsx?|docx?|csv|png|jpe?g|zip|txt|pptx?))", t, flags=re.I)
print("ext_count", len(exts))
print("ext_sample", exts[:40])
print("folder_ids", sorted(set(re.findall(r"/folders/([A-Za-z0-9_-]{20,})", t)))[:20])
print("file_ids", sorted(set(re.findall(r"/file/d/([A-Za-z0-9_-]{20,})", t)))[:20])

# Try gdown skip_download listing
try:
    import gdown
    files = gdown.download_folder(id=FOLDER_ID, skip_download=True, quiet=False)
    print("gdown_type", type(files))
    print("gdown_files", files)
except Exception as e:
    print("gdown_error", type(e).__name__, str(e))
