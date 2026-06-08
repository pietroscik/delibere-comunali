import re
import pandas as pd
from pathlib import Path

class DelibereExtractor:
    """
    Classe ottimizzata per l'estrazione strutturata di entità da testi di delibere e determine.
    Utilizza Regex avanzate per bypassare le inconsistenze dei parser PDF/OCR.
    """
    
    def __init__(self):
        # Pattern CIG: solitamente 10 caratteri alfanumerici, spesso preceduti dalla parola CIG
        self.cig_pattern = re.compile(r'\bCIG[\s:;]*([A-Z0-9]{10})\b', re.IGNORECASE)
        
        # Pattern CUP: solitamente 15 caratteri alfanumerici
        self.cup_pattern = re.compile(r'\bCUP[\s:;]*([A-Z0-9]{15})\b', re.IGNORECASE)
        
        # Pattern Importi: intercetta formati come "€ 10.980,00", "euro 18.000,00", "1.500,50 euro"
        self.importo_pattern = re.compile(r'(?:€|euro|importo\spari\sa)\s*(\d{1,3}(?:\.\d{3})*,\d{2})', re.IGNORECASE)
        
        # Pattern Partita IVA: 11 cifre numeriche precedute da P.IVA, PIVA, ecc.
        self.piva_pattern = re.compile(r'\bP\.?I\.?V\.?A\.?[\s:;]*(\d{11})\b', re.IGNORECASE)
        
        # Pattern IBAN: IT seguito da 2 cifre, 1 lettera e 22 cifre
        self.iban_pattern = re.compile(r'\b(IT\d{2}[A-Z]\d{22})\b', re.IGNORECASE)
        
        # Pattern Codice Appalti: D.Lgs 36/2023 o 50/2016
        self.appalti_pattern = re.compile(r'\bD\.?\s*Lgs\.?\s*(?:n\.?\s*)?(36/2023|50/2016)\b', re.IGNORECASE)
        
        # Pattern Importo in lettere (cerca testo tra parentesi vicino a parole chiave dell'importo)
        self.importo_lettere_pattern = re.compile(r'(?:€|euro)[\s\d\.,]+\s*\(([a-z\s]+(?:/\d{2})?)\)', re.IGNORECASE)

    def clean_text(self, text: str) -> str:
        """Rimuove interruzioni di riga e doppi spazi per facilitare il regex matching."""
        text = text.replace('\n', ' ').replace('\r', '')
        return re.sub(r'\s+', ' ', text)

    def _valida_partita_iva(self, piva: str) -> bool:
        """Applica l'algoritmo di Luhn (modulo 10) per verificare la validità di una Partita IVA italiana."""
        if not piva or len(piva) != 11 or not piva.isdigit():
            return False
        s = 0
        for i in range(11):
            c = int(piva[i])
            if i % 2 != 0:
                c *= 2
                if c > 9:
                    c -= 9
            s += c
        return s % 10 == 0
        
    def _valida_iban(self, iban: str) -> bool:
        """Validazione formale base dell'IBAN italiano (lunghezza 27 e prime 2 lettere IT)."""
        if not iban:
            return False
        iban = iban.replace(" ", "").upper()
        return iban.startswith("IT") and len(iban) == 27

    def extract_entities(self, text: str) -> dict:
        """
        Estrae le entità chiave dal testo di un atto amministrativo.
        Restituisce un dizionario con i dati estratti.
        """
        if not isinstance(text, str):
            return {}
            
        cleaned_text = self.clean_text(text)
        anomalie = []
        
        # Estrazione CIG (prende il primo trovato, o una lista univoca se necessario)
        cig_matches = self.cig_pattern.findall(cleaned_text)
        cig = cig_matches[0].upper() if cig_matches else None
        
        # Estrazione CUP
        cup_matches = self.cup_pattern.findall(cleaned_text)
        cup = cup_matches[0].upper() if cup_matches else None
        
        # Estrazione Importi (recupera tutti e trova il massimo, presumibilmente l'importo totale)
        importi_matches = self.importo_pattern.findall(cleaned_text)
        importo_max = None
        if importi_matches:
            # Converte le stringhe italiane (10.000,50) in float (10000.50)
            importi_float = [float(imp.replace('.', '').replace(',', '.')) for imp in importi_matches]
            importo_max = max(importi_float)
            
        # Estrazione importo letterale (es. milleduecento/00) per confronto umano/AI
        lettere_matches = self.importo_lettere_pattern.findall(cleaned_text)
        importo_lettere = lettere_matches[0].strip() if lettere_matches else None
            
        # Estrazione Partita IVA (utile per incrociare i beneficiari)
        piva_matches = self.piva_pattern.findall(cleaned_text)
        piva = piva_matches[0] if piva_matches else None
        
        if piva and not self._valida_partita_iva(piva):
            anomalie.append(f"Partita IVA {piva} formalmente errata (Checksum fallito)")

        # Estrazione IBAN
        iban_matches = self.iban_pattern.findall(cleaned_text)
        iban = iban_matches[0].upper() if iban_matches else None
        
        if iban and not self._valida_iban(iban):
            anomalie.append(f"IBAN {iban} formalmente errato (Lunghezza o nazione)")
            
        # Estrazione Codice Appalti
        appalti_matches = self.appalti_pattern.findall(cleaned_text)
        codice_appalti = appalti_matches[0] if appalti_matches else None

        return {
            "cig_estratto": cig,
            "cup_estratto": cup,
            "importo_max_estratto": importo_max,
            "importo_lettere": importo_lettere,
            "piva_beneficiario": piva,
            "iban_estratto": iban,
            "codice_appalti": codice_appalti,
            "anomalie_rilevate": " | ".join(anomalie) if anomalie else None
        }

def rielabora_dataset(input_csv_path: str, text_dir_path: str, output_csv_path: str):
    """
    Rielabora il file dei metadati incrociandolo con i file testuali per generare 
    un dataset ottimizzato.
    """
    extractor = DelibereExtractor()
    df = pd.read_csv(input_csv_path)
    
    extracted_data = []
    
    for index, row in df.iterrows():
        file_name = row.get('file_name', '')
        text_file = Path(text_dir_path) / f"{file_name}.txt"
        
        entities = {"file_name": file_name}
        if text_file.exists():
            with open(text_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                entities.update(extractor.extract_entities(content))
        else:
            entities.update({"cig_estratto": None, "cup_estratto": None, "importo_max_estratto": None, "piva_beneficiario": None})
            
        extracted_data.append(entities)
        
    df_extracted = pd.DataFrame(extracted_data)
    df_final = pd.merge(df, df_extracted, on='file_name', how='left')
    df_final.to_csv(output_csv_path, index=False)
    print(f"Dataset rielaborato e salvato in: {output_csv_path}")