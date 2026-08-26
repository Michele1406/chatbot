# SO FOOD - Assistente Virtuale "Nino"

Questo progetto implementa un chatbot basato su architettura RAG (Retrieval-Augmented Generation) per l'interrogazione del catalogo prodotti, delle informazioni aziendali e delle regole logistiche di SO FOOD.

## 1. Struttura del Progetto
* **`.env`**: File nascosto che contiene le credenziali (non versionato, da creare manualmente).
* **`.gitignore`**: File per escludere file sensibili (come `.env`) dal caricamento su GitHub.
* **`system_prompt.py`**: Contiene la personalità, le regole ferree e il tono di voce dell'assistente.
* **`caricaprodotti.py`**: Script per scansionare le cartelle locali del catalogo e mappare i prodotti nel database.
* **`carica_abstract_fornitori.py`**: Script per leggere il file `ABSTRACT.xlsx` e inserire le storie aziendali nel database.
* **`carica_logistica.py`**: Script per leggere i file `calendario_freschi.xlsx` e `consegne.xlsx` per inserire le regole di spedizione e tempistiche.
* **`main_chatbot.py`**: Il cuore dell'applicazione. Permette di chattare con Nino interrogando il database.
* **`database_vettoriale/`**: Cartella auto-generata contenente il database ChromaDB.

## 2. Lavorare con GitHub (Git Clone)
Poiché lo script `caricaprodotti.py` deve scansionare fisicamente cartelle e sottocartelle per verificare l'esistenza di file `.txt`, `.jpg` e `.pdf`, **non è possibile** far leggere i file direttamente dai link web di GitHub. 

Per lavorare a questo progetto, l'intera repository deve essere scaricata sul tuo computer locale:
1. Apri il terminale o GitHub Desktop.
2. Esegui il "Clone" della repository: `git clone [URL_DEL_TUO_REPO]`
3. Questo creerà una cartella locale sul tuo PC sincronizzata con GitHub, su cui gli script Python potranno lavorare alla massima velocità.

## 3. Architettura e Dettagli Tecnici (Context)
Il sistema sfrutta ChromaDB per l'archiviazione locale dei vettori e l'SDK di Google GenAI (modelli Gemini) sia per la generazione degli embeddings (`models/gemini-embedding-001`) che per l'inferenza del LLM (`gemini-3.5-flash-lite`).

* **Metadata Compatibility:** Il database ospita tre nature di dati differenti, armonizzate per non richiedere branching logico in fase di retrieval:
  1. *Prodotti:* Estratti da txt/pdf. I metadati tracciano allergeni, varianti, biologico, ecc.
  2. *Fornitori:* Estratti da foglio Excel. I metadati mimano la struttura dei prodotti.
  3. *Logistica:* Estratti dai fogli Excel delle consegne e calendari.
* **Strategia di Troncamento della Memoria (History):** Poiché l'SDK reinvia l'intera cronologia ad ogni chiamata, lo script `main_chatbot.py` applica una logica FIFO rigida per mantenere un massimo di `MAX_SCAMBI_STORICO * 2` messaggi. 
* **Sicurezza:** La chiave API è importata tramite `python-dotenv`. Le regole operative del bot (`system_prompt.py`) vietano all'intelligenza artificiale di rivelare meccanismi di funzionamento interni.

## 4. Installazione e Configurazione Iniziale
1. Assicurati di avere Python 3.10+ installato.
2. Installa le dipendenze richieste tramite il terminale:
   ```bash
   pip install -r requirements.txt