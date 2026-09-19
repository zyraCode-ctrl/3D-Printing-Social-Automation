"""Probe Google Drive shared folder listing without full download."""
from __future__ import annotations
import json, re, sys
import requests

FOLDER_ID = "14oA8BJi-MBQ7SYCl3rQZX-LkWgGwUI9j"
URLS = [
    f"https://drive.google.com/drive/folders/{FOLDER_ID}",
    f"https://drive.google.com/drive/folders/{FOLDER_ID}?usp=sharing",
    f"https://drive.google.com/embeddedfolderview?id={FOLDER_ID}",
]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

def probe(url: str) -> dict:
    r = requests.get(url, headers=HEADERS, timeout=60, allow_redirects=True)
    text = r.text
    titles = re.findall(r'"title":"([^"]{2,200})"', text)
    pairs = re.findall(r'\["(1[A-Za-z0-9_-]{10,})",\["([^"]+)"\]', text)
    return {
        "url": url,
        "status": r.status_code,
        "final_url": str(r.url),
        "len": len(text),
        "titles_sample": sorted(set(titles))[:40],
        "id_name_pairs": pairs[:40],
        "markers": {
            "drop_files": "Drop files here" in text,
            "need_access": ("You need access" in text) or ("Request access" in text),
            "sign_in": "Sign in" in text,
            "folder_empty": "This folder is empty" in text,
            "error_500": ("Error 500" in text) or ("That's an error" in text),
        },
    }

if __name__ == "__main__":
    print(json.dumps([probe(u) for u in URLS], indent=2, ensure_ascii=False))
