import subprocess
import sys
import os
from pathlib import Path

def run_script(script_name, args=[]):
    print(f"\n{'='*60}")
    print(f"🚀 ESECUZIONE: python {script_name} {' '.join(args)}")
    print(f"{'='*60}")
    
    result = subprocess.run([sys.executable, script_name] + args)
    
    if result.returncode != 0:
        print(f"\n❌ ERRORE CRITICO: Il processo {script_name} è fallito. Interruzione pipeline.")
        sys.exit(1)
    print(f"✅ Completato: {script_name}\n")

if __name__ == "__main__":
    # 1. Scraping (Opzionale: puoi decommentare la riga sotto se vuoi scaricare i dati freschi ogni volta)
    # run_script("albo_scraper.py", ["--page-from", "1", "--page-to", "20", "--out", "./albo_download", "--delay", "1.5"])

    # 2. Estrazione e Analisi (Crea i CSV e le features. Carica e usa il modello ML se esiste)
    run_script("analyze_albo.py", ["--base", "./albo_download"])

    # 3. Addestramento Intelligenza Artificiale (Opzionale, ma consigliato)
    # Usa i dati appena analizzati per (ri)addestrare la Random Forest e salvare il modello.
    ml_script = str(Path("albo_download") / "randomForest.py")
    if Path(ml_script).exists():
        run_script(ml_script)

    # 4. Pulizia Testi (Rimuove intestazioni e boilerplate burocratico per RAG e ML)
    run_script("clean_texts.py", ["--base", "./albo_download"])

    print("\n" + "🎉" * 20)
    print("PIPELINE COMPLETATA CON SUCCESSO!")
    print("🎉" * 20)
    
    print("\n▶️ Per esplorare la dashboard dei dati:")
    print(f"   {sys.executable} -m streamlit run visualizza_dati.py")
    
    print("\n▶️ Per avviare l'assistente RAG (Chatbot):")
    print(f"   {sys.executable} -m streamlit run rag_app.py")