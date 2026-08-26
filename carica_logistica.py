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
# CONFIGURAZIONE FILE
# ====================================================================
# Percorsi assoluti verso la cartella sofood
FILE_CALENDARIO = r"C:\Users\baron\LAVORO\PRODOTTI SOFOOD\sofood\calendario_freschi.xlsx"
FILE_CONSEGNE = r"C:\Users\baron\LAVORO\PRODOTTI SOFOOD\sofood\consegne.xlsx"
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

def carica_logistica():
    client_db = chromadb.PersistentClient(path=PERCORSO_DB)
    embedding_func = GoogleGeminiEmbeddingFunction(api_key=GEMINI_API_KEY, model_name=MODELLO_EMBEDDING)
    collezione = client_db.get_or_create_collection(name=NOME_COLLEZIONE, embedding_function=embedding_func)
    
    dati_esistenti = collezione.get()
    id_gia_salvati = set(dati_esistenti.get("ids", []))

    documenti = []
    metadati = []
    ids = []

    # ==========================================================
    # 1. ELABORAZIONE CALENDARIO FRESCHI
    # ==========================================================
    if os.path.exists(FILE_CALENDARIO):
        print(f"[INFO] Lettura file {FILE_CALENDARIO}...")
        try:
            df_cal = pd.read_excel(FILE_CALENDARIO, sheet_name="Calendario Ordini", dtype=str)
            for _, row in df_cal.iterrows():
                azienda = str(row.get('NOME AZIENDA', '')).strip()
                giorno_ordine = str(row.get("GIORNO ENTRO CUI FARE L'ORDINE", '')).strip()
                giorno_arrivo = str(row.get('GIORNO ARRIVO', '')).strip()

                if azienda and azienda != 'nan':
                    testo = f"--- CALENDARIO ORDINI FRESCHI ---\n"
                    testo += f"Fornitore / Azienda: {azienda}\n"
                    testo += f"Giorno limite per inviare l'ordine: {giorno_ordine}\n"
                    testo += f"Giorno previsto di arrivo merce: {giorno_arrivo}\n"

                    doc_id = f"CALENDARIO_{azienda.replace(' ', '_')}"
                    meta = {
                        "nome_fornitore": azienda,
                        "categoria_prodotto": "INFO LOGISTICA E ORDINI",
                        "varianti_prodotto": "Calendario Freschi"
                    }

                    if doc_id not in id_gia_salvati:
                        documenti.append(testo)
                        metadati.append(meta)
                        ids.append(doc_id)
        except Exception as e:
            print(f"[ERRORE] Elaborazione calendario fallita: {e}")
    else:
        print(f"[AVVISO] File {FILE_CALENDARIO} non trovato.")

    # ==========================================================
    # 2. ELABORAZIONE PROGRAMMA CONSEGNE
    # ==========================================================
    if os.path.exists(FILE_CONSEGNE):
        print(f"[INFO] Lettura file {FILE_CONSEGNE}...")
        try:
            df_cons = pd.read_excel(FILE_CONSEGNE, sheet_name="Programma Consegne", dtype=str)
            
            # Rimuoviamo eventuali righe vuote o righe di sola intestazione extra
            df_cons = df_cons.dropna(subset=['NOME'])

            for _, row in df_cons.iterrows():
                zona = str(row.get('NOME', '')).strip()
                if not zona or zona == 'nan':
                    continue

                id_zona = str(row.get('ZONA (ID)', '')).strip()
                pagamento = str(row.get('METODI DI PAGAMENTO', '')).strip()
                minimo_ordine = str(row.get('MINIMO ORDINE PER CONSEGNA GRATUITA', '')).strip()
                costo_sped = str(row.get('COSTI SPEDIZIONE ', row.get('COSTI SPEDIZIONE', ''))).strip()
                tempi = str(row.get('TEMPI MEDI', '')).strip()
                condizioni = str(row.get('CONDIZIONI DI CONSEGNA', '')).strip()
                sede = str(row.get('SEDE LEGALE', '')).strip()
                deposito = str(row.get('DEPOSITO', '')).strip()

                testo = f"--- PROGRAMMA SPEDIZIONI E CONSEGNE ---\n"
                testo += f"Zona di Consegna: {zona} (ID: {id_zona})\n"
                testo += f"Tempi medi di consegna: {tempi}\n"
                testo += f"Minimo ordine per consegna gratuita: {minimo_ordine}\n"
                testo += f"Costo spedizione (se minimo non raggiunto): {costo_sped}\n"
                testo += f"Metodi di pagamento accettati: {pagamento}\n"
                testo += f"Condizioni di consegna: {condizioni}\n"
                testo += f"Sede Legale: {sede}\n"
                testo += f"Deposito logistico: {deposito}\n"

                doc_id = f"CONSEGNA_{zona.replace(' ', '_').upper()}"
                meta = {
                    "nome_fornitore": "SO FOOD (Logistica Interna)",
                    "categoria_prodotto": "REGOLE DI CONSEGNA ZONALE",
                    "varianti_prodotto": f"Spedizioni {zona}"
                }

                if doc_id not in id_gia_salvati:
                    documenti.append(testo)
                    metadati.append(meta)
                    ids.append(doc_id)
        except Exception as e:
            print(f"[ERRORE] Elaborazione consegne fallita: {e}")
    else:
        print(f"[AVVISO] File {FILE_CONSEGNE} non trovato.")

    # ==========================================================
    # 3. SCRITTURA NEL DATABASE
    # ==========================================================
    if documenti:
        print(f"[INFO] Inserimento di {len(documenti)} regole logistiche nel database...")
        for i in range(len(documenti)):
            collezione.add(
                documents=[documenti[i]],
                metadatas=[metadati[i]],
                ids=[ids[i]]
            )
            print(f"   [OK] Indicizzato: {ids[i]}")
        print("\n[SUCCESSO] Dati logistici aggiunti al database vettoriale!")
    else:
        print("\n[INFO] Nessuna nuova regola da aggiungere. Database già aggiornato.")

if __name__ == "__main__":
    carica_logistica()