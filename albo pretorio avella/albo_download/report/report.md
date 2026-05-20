# Report Albo Pretorio Avella

## Sintesi

- PDF/documenti analizzati: 759
- Allegati parsed: 759
- Righe metadati: 1047
- Parole medie per documento: 1305.3
- Parole mediane per documento: 699.0
- Documenti senza categoria: 31 (4.08%)
- Classificazioni ambigue: 0 (0.0%)

## Priorita' Di Ottimizzazione

- P1 `metadati_senza_tipologia`: 726/1047 (69.34%). Rigenerare metadati puliti o ricavare tipologia dagli allegati.
- P1 `documenti_senza_importi`: 290/759 (38.21%). Dato descrittivo: molti atti non devono contenere importi.
- P2 `atti_contabili_senza_importi`: 92/759 (12.12%). Priorita' reale: migliorare regex importi/OCR sui soli atti contabili.
- P2 `testi_troppo_corti`: 80/759 (10.54%). Controllare OCR, PDF vuoti o allegati non deliberativi.
- P3 `documenti_senza_categoria`: 31/759 (4.08%). Ampliare dizionario categorie o passare a classificazione supervisionata.
- P3 `tipo_documento_unknown`: 24/759 (3.16%). Migliorare inferenza tipo da filename/testo.
- P3 `testi_duplicati`: 18/759 (2.37%). Deduplicare corpus prima di training/embedding.

## Ciclo Ricorsivo Consigliato

1. Misura: rigenera questo report dopo ogni scraping/analisi.
2. Correggi: affronta prima le criticita' P1 e P2.
3. Valida: controlla manualmente un campione di documenti ambigui/non categorizzati.
4. Addestra: usa `documenti_corpus.jsonl` solo dopo deduplica e controllo OCR.
5. Ripeti: confronta percentuali e distribuzioni tra iterazioni.

## Output Generati

- `albo_download\report\quality_issues.csv`
- `albo_download\report\category_distribution.csv`
- `albo_download\report\category_numeric_profile.csv`
- `albo_download\report\albo_exploration.xlsx`

## Campione Corpus

- `atto_10__5386_OrdinanzeSindacali_Copia_10_2026_1.pdf` | Ordinanza | Contenzioso: COPIA Piazza Municipio n. 1, C.A.P: 83021 - Avella (AV); P. IVA 00248800641; Tel/Fax 081.8259343; PEC: comune.avella@cert.irpinianet.eu; http://www.comune.avella.av.it. COMUNE DI AVELLA (Provincia di Avellino) Città d'Arte ORDINANZA SINDACA...
- `atto_10__5415_DecretoSindacale_Copia_10_2026_1.pdf` | Decreto | nan: COPIA Piazza Municipio I, 83021 Avella (AV); P. IVA n. 00248800641; Tel. 081.8259311; Fax 081.8259315; PEC comune.avella@cert.irpinianet.eu; http://www.comune.avella.av.it. COMUNE DI AVELLA (Provincia di Avellino) Città d'Arte DECRETO SINDA...
- `atto_11__5442_DecretoSindacale_Copia_11_2026_1.pdf` | Decreto | Regolamenti: COPIA Piazza Municipio I, 83021 Avella (AV); P. IVA n. 00248800641; Tel. 081.8259311; Fax 081.8259315; PEC comune.avella@cert.irpinianet.eu; http://www.comune.avella.av.it. COMUNE DI AVELLA (Provincia di Avellino) Città d'Arte DECRETO SINDA...
