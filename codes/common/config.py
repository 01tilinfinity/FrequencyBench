import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"
RAW, PROCESSED, FINAL = DATA / "raw", DATA / "processed", DATA / "final"
for d in (RAW, PROCESSED, FINAL):
    d.mkdir(parents=True, exist_ok=True)

CONTACT = os.getenv("WDQS_CONTACT", "hs01151116@korea.ac.kr")
UA = {"User-Agent": f"FrequencyBench/0.1 ({CONTACT})"}

def api_key(provider):
    k = {"claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
         "glm": "GLM_API_KEY"}[provider]
    v = os.getenv(k)
    if not v:
        raise SystemExit(f"{k} not set in .env")
    return v