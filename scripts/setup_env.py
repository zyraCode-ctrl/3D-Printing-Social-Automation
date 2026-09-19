#!/usr/bin/env python3
"""Create .env from .env.example with generated secrets if missing."""

from __future__ import annotations

import secrets
import string
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / ".env.example"
ENV = ROOT / ".env"


def password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    body = "".join(secrets.choice(alphabet) for _ in range(length - 2))
    return "Aa1!" + body


def main() -> None:
    if ENV.exists():
        print(f".env already exists at {ENV}")
        return
    text = EXAMPLE.read_text(encoding="utf-8")
    text = text.replace("replace-with-32-plus-random-characters", secrets.token_hex(32))
    text = text.replace("replace-with-strong-password", password())
    ENV.write_text(text, encoding="utf-8")
    print(f"Wrote {ENV} with a generated encryption key and owner password.")
    print("DRY_RUN=true and USE_SAMPLE_MEDIA=true remain the defaults.")


if __name__ == "__main__":
    main()
