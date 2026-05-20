import pandas as pd
from analyze_albo import ocr_pdf_full
from pathlib import Path
import os
import sys

# --- CONFIGURATION ---
PDF_TO_DEBUG = "atto_19922025__Vai_3.php"
# Use an absolute path evaluated at runtime
PROJECT_DIR = Path(__file__).resolve().parent
PDF_DIR = PROJECT_DIR / "albo_download" / "pdf"

# --- SCRIPT ---
# Set stdout to utf-8
sys.stdout.reconfigure(encoding='utf-8')

pdf_path = PDF_DIR / PDF_TO_DEBUG

if not pdf_path.exists():
    print(f"ERRORE: Il file '{pdf_path}' non è stato trovato.")
else:
    print(f"--- ANALISI TESTO PER: {PDF_TO_DEBUG} ---")
    text = ocr_pdf_full(pdf_path)
    print(text)
    print("\n--- FINE ANALISI ---")