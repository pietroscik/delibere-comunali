# Report Albo Pretorio Avella

## Sintesi

- PDF/documenti analizzati: 1503
- Allegati parsed: 1503
- Righe metadati: 1456
- Parole medie per documento: 1189.1
- Parole mediane per documento: 677.0
- Documenti senza categoria: 53 (3.53%)
- Classificazioni ambigue: 52 (3.46%)

## Priorita' Di Ottimizzazione

- P1 `metadati_senza_tipologia`: 792/1456 (54.4%). Rigenerare metadati puliti o ricavare tipologia dagli allegati.
- P1 `documenti_senza_importi`: 479/1503 (31.87%). Dato descrittivo: molti atti non devono contenere importi.
- P3 `atti_contabili_senza_importi`: 148/1503 (9.85%). Priorita' reale: migliorare regex importi/OCR sui soli atti contabili.
- P3 `testi_troppo_corti`: 110/1503 (7.32%). Controllare OCR, PDF vuoti o allegati non deliberativi.
- P3 `documenti_senza_categoria`: 53/1503 (3.53%). Ampliare dizionario categorie o passare a classificazione supervisionata.
- P3 `classificazioni_ambigue`: 52/1503 (3.46%). Revisionare manualmente e usare come validation set.
- P3 `tipo_documento_unknown`: 32/1503 (2.13%). Migliorare inferenza tipo da filename/testo.

## Ciclo Ricorsivo Consigliato

1. Misura: rigenera questo report dopo ogni scraping/analisi.
2. Correggi: affronta prima le criticita' P1 e P2.
3. Valida: controlla manualmente un campione di documenti ambigui/non categorizzati.
4. Addestra: usa `documenti_corpus.jsonl` solo dopo deduplica e controllo OCR.
5. Ripeti: confronta percentuali e distribuzioni tra iterazioni.

## Output Generati

- `C:\Users\39329\OneDrive - Uniparthenope\delibere comunali\albo pretorio avella\albo_download\report\quality_issues.csv`
- `C:\Users\39329\OneDrive - Uniparthenope\delibere comunali\albo pretorio avella\albo_download\report\category_distribution.csv`
- `C:\Users\39329\OneDrive - Uniparthenope\delibere comunali\albo pretorio avella\albo_download\report\doc_type_distribution.csv`
- `C:\Users\39329\OneDrive - Uniparthenope\delibere comunali\albo pretorio avella\albo_download\report\source_distribution.csv`
- `C:\Users\39329\OneDrive - Uniparthenope\delibere comunali\albo pretorio avella\albo_download\report\confidence_distribution.csv`
- `C:\Users\39329\OneDrive - Uniparthenope\delibere comunali\albo pretorio avella\albo_download\report\category_numeric_profile.csv`
- `C:\Users\39329\OneDrive - Uniparthenope\delibere comunali\albo pretorio avella\albo_download\report\doctype_category_matrix.csv`
- `C:\Users\39329\OneDrive - Uniparthenope\delibere comunali\albo pretorio avella\albo_download\report\short_text_documents.csv`
- `C:\Users\39329\OneDrive - Uniparthenope\delibere comunali\albo pretorio avella\albo_download\report\long_text_documents.csv`
- `C:\Users\39329\OneDrive - Uniparthenope\delibere comunali\albo pretorio avella\albo_download\report\top_importi.csv`
- `C:\Users\39329\OneDrive - Uniparthenope\delibere comunali\albo pretorio avella\albo_download\report\ambiguous_documents.csv`
- `C:\Users\39329\OneDrive - Uniparthenope\delibere comunali\albo pretorio avella\albo_download\report\uncategorized_documents.csv`
- `C:\Users\39329\OneDrive - Uniparthenope\delibere comunali\albo pretorio avella\albo_download\report\albo_exploration.xlsx`

## Campione Corpus

- `atto_10__5386_OrdinanzeSindacali_Copia_10_2026_1.pdf` | Ordinanza | Contenzioso: ORDINANZA SINDACALE N. 10 DEL 16/03/2026 OGGETTO: Chiusura dei plessi scolastici dell’Istituto Comprensivo “Mons. Pasquale Guerriero” di Avella per lo svolgimento delle consultazioni referendarie del 22 e 23 marzo 2026. IL SINDACO Premesso ...
- `atto_10__5415_DecretoSindacale_Copia_10_2026_1.pdf` | Decreto | nan: DECRETO SINDACALE N. 10 DEL 25/03/2026 OGGETTO: Nomina del Gestore delle segnalazioni in materia di Antiriciclaggio e Finanziamento del Terrorismo del Comune di Avella. VISTI: - il D.lgs. 22.06.2007 n. 109 recante “Misure per prevenire, con...
- `atto_11__5442_DecretoSindacale_Copia_11_2026_1.pdf` | Decreto | Regolamenti: DECRETO SINDACALE N. 11 DEL 31/03/2026 OGGETTO: Rinnovo del decreto di nomina Vice Segretario del Comune di Avella (Prov. AV) al dipendente Avv. Massimiliano SORRIENTO PREMESSO: CHE questa Amministrazione, con deliberazione di Giunta Comuna...
