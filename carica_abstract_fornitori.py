import os
import pandas as pd
import chromadb
from google import genai
from dotenv import load_dotenv

# Carica le variabili d'ambiente dal file .env
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("ATTENZIONE: API Key mancante nel file .env")

# ====================================================================
# CONFIGURAZIONE
# ====================================================================
# Percorso assoluto aggiornato
FILE_EXCEL_ABSTRACT = r"C:\Users\baron\LAVORO\PRODOTTI SOFOOD\sofood\ABSTRACT.xlsx"
NOME_FOGLIO = "Abstract Database"
PERCORSO_DB = "./database_vettoriale"
NOME_COLLEZIONE = "catalogo_sofood"
MODELLO_EMBEDDING = "models/gemini-embedding-001"

class GoogleGeminiEmbeddingFunction(chromadb.EmbeddingFunction):
    def __init__(self, api_key: str, model_name: str):
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name

    def __call__(self, input: list[str]) -> list[list[float]]:
        embeddings = []
        for text in input:
            response = self.client.models.embed_content(
                model=self.model_name,
                contents=text
            )
            res_emb = response.embeddings[0]
            vector = res_emb.values if hasattr(res_emb, "values") else list(res_emb)
            embeddings.append(vector)
        return embeddings

def carica_fornitori():
    print(f"[INFO] Lettura file {FILE_EXCEL_ABSTRACT}...")
    try:
        # Leggiamo tutto come stringa per evitare problemi coi codici fornitore
        df = pd.read_excel(FILE_EXCEL_ABSTRACT, sheet_name=NOME_FOGLIO, dtype=str)
    except Exception as e:
        print(f"[ERRORE] Impossibile leggere il file Excel: {e}")
        return

    # Il file ha celle unite/vuote. Copiamo il valore della riga precedente (forward fill)
    colonne_da_riempire = ['an_forn', 'NOME_AZIENDA', 'RAGIONE_SOCIALE', 'TIPOLOGIA (CATALOGO DI APPARTENENZA)']
    for col in colonne_da_riempire:
        if col in df.columns:
            df[col] = df[col].ffill()

    print("[INFO] Connessione a ChromaDB...")
    client_db = chromadb.PersistentClient(path=PERCORSO_DB)
    embedding_func = GoogleGeminiEmbeddingFunction(api_key=GEMINI_API_KEY, model_name=MODELLO_EMBEDDING)
    collezione = client_db.get_or_create_collection(name=NOME_COLLEZIONE, embedding_function=embedding_func)

    # Rilevamento ID già presenti per inserimento incrementale
    dati_esistenti = collezione.get()
    id_gia_salvati = set(dati_esistenti.get("ids", []))

    documenti = []
    metadati = []
    ids = []

    print("[INFO] Generazione schede fornitori...")
    # Raggruppiamo i blocchi di testo per singolo fornitore
    for (an_forn, nome), group in df.groupby(['an_forn', 'NOME_AZIENDA']):
        
        testo = f"--- STORIA E VALORI DEL FORNITORE ---\n"
        testo += f"Azienda: {nome} (Codice: {an_forn})\n"
        if 'RAGIONE_SOCIALE' in group.columns:
            testo += f"Ragione Sociale: {group['RAGIONE_SOCIALE'].iloc[0]}\n"
        testo += "\n"
        
        for _, row in group.iterrows():
            campo = str(row.get('CAMPO INFORMATIVO', '')).strip()
            contenuto = str(row.get('CONTENUTO', '')).strip()
            if campo and campo != 'nan' and contenuto and contenuto != 'nan':
                testo += f"[{campo.upper()}]\n{contenuto}\n\n"
        
        doc_id = f"FORNITORE_{an_forn}_{nome.replace(' ', '_')}"
        
        # Usiamo le stesse chiavi di main_chatbot.py per massima compatibilità
        meta = {
            "nome_fornitore": nome,
            "categoria_prodotto": "SCHEDA AZIENDALE FORNITORE",
            "varianti_prodotto": "Info Storiche/Aziendali"
        }

        if doc_id not in id_gia_salvati:
            documenti.append(testo)
            metadati.append(meta)
            ids.append(doc_id)

    if documenti:
        print(f"[INFO] Inserimento di {len(documenti)} fornitori nel database...")
        for i in range(len(documenti)):
            collezione.add(
                documents=[documenti[i]],
                metadatas=[metadati[i]],
                ids=[ids[i]]
            )
            print(f"   [OK] Indicizzato: {ids[i]}")
        print("\n[SUCCESSO] Fornitori aggiunti al database vettoriale!")
    else:
        print("\n[INFO] Nessun nuovo fornitore da aggiungere. Database già aggiornato.")

if __name__ == "__main__":
    carica_fornitori()