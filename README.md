# Albo Pretorio Avella

Pipeline Python per:

1. scraping metadati e allegati pubblici dall'Albo Pretorio OpenWeb del Comune di Avella,
2. analisi/estrazione dati dai PDF,
3. validazione qualita',
4. esplorazione reportistica,
5. consultazione RAG (locale o Gemini).

## Panoramica Rapida

Flusso consigliato end-to-end:

1. `albo_scraper.py` -> scarica metadati + allegati in `albo_download/`.
2. `analyze_albo.py` -> estrae testo/campi e crea dataset analitici.
3. `validate_output.py` -> controlli automatici su schema/qualita'.
4. `explore_albo.py` -> report esplorativi e priorita' operative.
5. `rag_app.py` / `visualizza_dati.py` -> consultazione interattiva.

## Installazione

```bash
cd "albo pretorio avella"
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
# opzionale: training ML
python3 -m pip install -r requirements-ml.txt
# opzionale: dashboard + RAG
python3 -m pip install -r requirements-rag.txt
```

Su PowerShell, dopo attivazione venv, usa `python` al posto di `python3`.

Configurazione variabili (consigliata prima del RAG):

```bash
cp .env.example .env
# poi modifica .env (almeno GOOGLE_API_KEY se usi Gemini)
```

Note:

- `requirements.txt` contiene solo il core (scraping + analisi).
- OCR richiede Tesseract installato nel sistema.
- L'estrazione da file `.p7m` (firma digitale) è supportata nativamente tramite `pythonnet` o `openssl` se presente nel PATH.
- Su Windows viene provato automaticamente `C:\Program Files\Tesseract-OCR\tesseract.exe`.

## Quickstart

Esegui un ciclo base completo:

```bash
python3 albo_scraper.py --page-from 1 --page-to 20 --out ./albo_download --delay 1.5
python3 analyze_albo.py --base ./albo_download
python3 validate_output.py --base ./albo_download
python3 explore_albo.py --base ./albo_download
```

## Flussi Operativi

### 1) Solo Scraping

```bash
python3 albo_scraper.py --page-from 1 --page-to 80 --only-types Delibera --no-download
python3 albo_scraper.py --page-from 1 --page-to 80 --title-regex "bilancio|rendiconto"
```

`albo_scraper.py` e' l'entry point pubblico e delega a `new_albo_scraper.py`.

### 2) Analisi e Validazione

```bash
python3 analyze_albo.py --base ./albo_download
python3 verify_output.py --excel ./albo_download/albo_analisi.xlsx
python3 validate_output.py --base ./albo_download
# strict mode (warning bloccanti)
python3 validate_output.py --base ./albo_download --fail-on-warning
```

Codici uscita `validate_output.py`:

- `0`: output coerente (anche con warning non bloccanti).
- `1`: warning presenti con `--fail-on-warning`.
- `2`: errori bloccanti (schema/file/duplicati chiave).

### 3) Pipeline Orchestrata

```bash
python3 run_pipeline.py
# variante veloce senza training ML
python3 run_pipeline.py --skip-ml
# includi pulizia testi (boilerplate) prima della validazione
python3 run_pipeline.py --clean-texts
# validazione strict (warning bloccanti)
python3 run_pipeline.py --strict-validation
```

Flusso `run_pipeline.py`:

1. `analyze_albo.py`
2. (se non `--skip-ml`) `albo_download/randomForest.py`
3. (se non `--skip-ml`) `analyze_albo.py` secondo pass con modello
4. (se `--clean-texts`) `clean_texts.py`
5. `validate_output.py` (con `--fail-on-warning` se `--strict-validation`)

### 4) Dashboard e RAG

```bash
python3 -m streamlit run visualizza_dati.py
python3 -m streamlit run rag_app.py
```

## Output Principali

- `albo_download/albo_metadati.csv`: metadati scraping.
- `albo_download/allegati_parsed.csv`: estrazioni per documento.
- `albo_download/documenti_features.csv`: feature analitiche.
- `albo_download/documenti_corpus.jsonl`: corpus RAG/ML.
- `albo_download/texts/*.txt`: testo normalizzato per file.
- `albo_download/albo_analisi.xlsx`: output tabellare multi-sheet.
- `albo_download/failed_extractions.csv`: file scartati/non validi.
- `albo_download/report/*`: report prodotti da `explore_albo.py`.

**Nota sulla qualità del testo estratto:**
I file in `texts/` e il campo `text` in `documenti_corpus.jsonl` contengono il testo estratto dai PDF. Questo testo include spesso boilerplate (intestazioni e piè di pagina ripetuti come `"COPIA Piazza Municipio..."`) e sezioni burocratiche standard a fine documento (es. `"PARERE DI REGOLARITÀ TECNICA"`, `"ATTESTAZIONE DI PUBBLICAZIONE"`). Per task di analisi NLP o RAG, è consigliabile pre-processare il testo per rimuovere queste parti ridondanti. Inoltre, l'analisi corrente non estrae sistematicamente tutti i dati strutturati presenti, come i codici **CIG** (Codice Identificativo Gara), che sono spesso visibili nel testo (es. `CIG: BA980C4973`).

## Ciclo di Ottimizzazione della Qualità

L'esecuzione di `explore_albo.py` produce un `report.md` con una sintesi dei problemi di qualità e un ciclo operativo consigliato per migliorare progressivamente i dati estratti. Il flusso iterativo è:

1.  **Misura**: rigenera i report (`explore_albo.py`) dopo ogni scraping o modifica all'analisi per avere una baseline aggiornata.
2.  **Correggi**: affronta le criticità con priorità P1 e P2 evidenziate nel report (es. `metadati_senza_tipologia`, `atti_contabili_senza_importi`). Questo potrebbe richiedere modifiche allo script `analyze_albo.py`.
3.  **Valida**: controlla manualmente un campione di documenti segnalati come ambigui o non categorizzati. Questi documenti sono candidati ideali per costruire un *validation set* per futuri modelli di classificazione.
4.  **Addestra**: usa il corpus pulito e deduplicato (`documenti_corpus.jsonl`) per addestrare modelli ML o per alimentare il sistema RAG, solo dopo aver verificato la qualità dell'OCR e del testo.
5.  **Ripeti**: confronta le percentuali e le distribuzioni nei report tra le varie iterazioni per misurare i miglioramenti.

## RAG Quota-Aware

`rag_app.py` e' ottimizzato per quote diverse:

1. profili in sidebar (`Conservativo`, `Bilanciato`, `Prestazioni`);
2. fallback automatico tra modelli LLM;
3. cooldown 60s sui modelli in `429 RESOURCE_EXHAUSTED`;
4. build embeddings a batch + pausa configurabile;
5. modalita' Gemini con retriever locale (zero quota embedding);
6. modalita' locale senza API disponibile sempre.

Variabili `.env` utili:

```bash
RAG_USE_GEMINI_BY_DEFAULT=true
RAG_USE_LOCAL_RETRIEVER_WITH_GEMINI=true
GOOGLE_LLM_MODEL=gemini-2.5-flash
GOOGLE_EMBEDDING_MODEL=models/gemini-embedding-001
GOOGLE_LLM_MODEL_PRIORITY=gemini-3.1-flash-lite,gemini-2.5-flash-lite,gemini-2.5-flash
GOOGLE_EMBEDDING_MODEL_PRIORITY=models/gemini-embedding-001,models/text-embedding-004
```

## Struttura File

- `albo_scraper.py`: entry point scraping.
- `new_albo_scraper.py`: implementazione scraping.
- `analyze_albo.py`: parsing PDF, estrazione metadati e feature.
- `validate_output.py`: quality gate dataset.
- `explore_albo.py`: report esplorativi ricorsivi.
- `run_pipeline.py`: orchestration analisi + ML.
- `rag_app.py`: chatbot RAG locale/Gemini quota-aware.
- `visualizza_dati.py`: dashboard Streamlit per validazione manuale.
- `tests/`: test di regressione.

## Pubblicazione Git

Il repository include un `.gitignore` che esclude venv e segreti.
La cartella `albo_download/` e' mantenuta versionata intenzionalmente per
analizzare e validare la qualita' degli output nel tempo.
Per sicurezza:

1. usa sempre `.env` locale (mai committarlo),
2. versiona solo `.env.example`,
3. verifica prima del push con `git status`.

## Test Rapidi

```bash
python3 -m unittest discover -s tests -p "test_*.py"
python3 -m pytest -q
python3 -m py_compile *.py
```

## Troubleshooting

`No module named streamlit`:

```bash
python -m pip install -r requirements-rag.txt
```

`GOOGLE_API_KEY non trovata`:

```bash
echo "GOOGLE_API_KEY=la_tua_chiave" > .env
```

`404 NOT_FOUND` su embedding:

```bash
echo "GOOGLE_EMBEDDING_MODEL=models/gemini-embedding-001" >> .env
```

`429 RESOURCE_EXHAUSTED`:

1. usa modalita' locale oppure profilo `Conservativo`,
2. attiva toggle `Gemini con retriever locale (zero quota embedding)`,
3. riduci `Batch embedding` e aumenta `Pausa batch embedding`,
4. usa priorita' modello con fallback in `.env`,
5. riprova dopo reset quota o aggiorna piano/billing.
