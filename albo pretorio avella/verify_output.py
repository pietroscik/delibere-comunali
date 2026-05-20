import argparse
from pathlib import Path

import pandas as pd
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_EXCEL_PATH = SCRIPT_DIR / "albo_download" / "albo_analisi.xlsx"
SHEET_NAME_ANALISI = "pdf_analisi"

# --- SCRIPT ---
# Set stdout to utf-8
sys.stdout.reconfigure(encoding='utf-8')

def main():
    ap = argparse.ArgumentParser(description="Mostra i documenti non classificati nell'Excel di analisi.")
    ap.add_argument("--excel", default=str(DEFAULT_EXCEL_PATH), help="Percorso del file albo_analisi.xlsx")
    args = ap.parse_args()

    try:
        df_analisi = pd.read_excel(args.excel, sheet_name=SHEET_NAME_ANALISI)

        unclassified = df_analisi[df_analisi['category'].isna()]

        if not unclassified.empty:
            print("--- Unclassified Documents ---")
            print(unclassified.to_string())
        else:
            print("All documents have been classified.")

    except FileNotFoundError:
        print(f"ERRORE: Il file '{args.excel}' non è stato trovato.")
    except Exception as e:
        print(f"ERRORE: Impossibile leggere il file Excel. Dettagli: {e}")


if __name__ == "__main__":
    main()
