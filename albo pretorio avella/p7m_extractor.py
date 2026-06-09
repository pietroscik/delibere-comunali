#!/usr/bin/env python3
import subprocess
import os
from pathlib import Path

def extract_p7m(input_dir, output_dir="albo_download/allegati_decapsulati"):
    """
    Estrae PDF da file .p7m usando OpenSSL (Windows).
    Args:
        input_dir (str): Cartella con file .p7m.
        output_dir (str): Cartella di output per PDF estratti.
    Returns:
        list: Percorsi dei PDF estratti.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    extracted_files = []

    # Percorso di OpenSSL in Windows (default)
    openssl_path = r'C:\Program Files\OpenSSL-Win64\bin\openssl.exe'
    if not os.path.exists(openssl_path):
        openssl_path = 'openssl'  # Prova nel PATH

    for file in os.listdir(input_dir):
        if file.endswith('.p7m'):
            input_file = os.path.join(input_dir, file)
            output_file = os.path.join(output_dir, file.replace('.p7m', '.pdf'))

            try:
                subprocess.run(
                    [
                        openssl_path, 'smime', '-verify',
                        '-in', input_file,
                        '-out', output_file,
                        '-noverify'
                    ],
                    check=True,
                    capture_output=True,
                    text=True
                )
                extracted_files.append(output_file)
                print(f"✅ Estratto: {file} -> {output_file}")
            except subprocess.CalledProcessError as e:
                print(f"❌ Errore su {file}: {e.stderr}")
            except FileNotFoundError:
                print(f"❌ OpenSSL non trovato. Installa OpenSSL per Windows o aggiungi al PATH.")

    return extracted_files

if __name__ == "__main__":
    import sys
    input_dir = sys.argv[1] if len(sys.argv) > 1 else "albo_download/allegati"
    extract_p7m(input_dir)