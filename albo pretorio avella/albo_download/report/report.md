# Report Albo Pretorio Avella

## Sintesi

- PDF/documenti analizzati: 1530
- Allegati parsed: 1530
- Righe metadati: 1456
- Parole medie per documento: 1306.9
- Parole mediane per documento: 698.0
- Documenti senza categoria: 2 (0.13%)
- Classificazioni ambigue: 0 (0.0%)

## Priorita' Di Ottimizzazione

- P1 `metadati_senza_tipologia`: 792/1456 (54.4%). Rigenerare metadati puliti o ricavare tipologia dagli allegati.
- P1 `documenti_senza_importi`: 514/1530 (33.59%). Dato descrittivo: molti atti non devono contenere importi.
- P2 `atti_contabili_senza_importi`: 174/1530 (11.37%). Priorita' reale: migliorare regex importi/OCR sui soli atti contabili.
- P3 `testi_troppo_corti`: 117/1530 (7.65%). Controllare OCR, PDF vuoti o allegati non deliberativi.
- P3 `tipo_documento_unknown`: 35/1530 (2.29%). Migliorare inferenza tipo da filename/testo.
- P3 `testi_duplicati`: 26/1530 (1.7%). Deduplicare corpus prima di training/embedding.
- P3 `documenti_senza_categoria`: 2/1530 (0.13%). Ampliare dizionario categorie o passare a classificazione supervisionata.

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
- `atto_10__5415_DecretoSindacale_Copia_10_2026_1.pdf` | Decreto | Contabilità: COPIA Piazza Municipio I, 83021 Avella (AV); P. IVA n. 00248800641; Tel. 081.8259311; Fax 081.8259315; PEC comune.avella@cert.irpinianet.eu; http://www.comune.avella.av.it. COMUNE DI AVELLA (Provincia di Avellino) Città d'Arte DECRETO SINDA...
- `atto_11__5442_DecretoSindacale_Copia_11_2026_1.pdf` | Decreto | Regolamenti: COPIA Piazza Municipio I, 83021 Avella (AV); P. IVA n. 00248800641; Tel. 081.8259311; Fax 081.8259315; PEC comune.avella@cert.irpinianet.eu; http://www.comune.avella.av.it. COMUNE DI AVELLA (Provincia di Avellino) Città d'Arte DECRETO SINDA...
