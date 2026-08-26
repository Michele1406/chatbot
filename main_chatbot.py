import os
import chromadb
from chromadb.utils import embedding_functions
from google import genai
from google.genai import types
from system_prompt import SYSTEM_PROMPT_NINO
from dotenv import load_dotenv

# Carica le variabili d'ambiente dal file .env
load_dotenv()

# ====================================================================
# CONFIGURAZIONE
# ====================================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("ATTENZIONE: GEMINI_API_KEY non trovata. Controlla di aver creato correttamente il file .env")

SCELTA_EMBEDDING = "google-001" # "google-001", "google-2" o "locale"
PERCORSO_DATABASE_VETTORIALE = "./database_vettoriale"
NOME_COLLEZIONE = "catalogo_sofood"
MODELLO_GEMINI = "models/gemini-3.5-flash-lite"

# Quanti prodotti recupera il RAG ad ogni domanda (meno prodotti = meno token
# di contesto reinviati ad ogni turno, a scapito di qualche match secondario)
N_RISULTATI_RAG = 6

# Quanti scambi (utente + risposta di Nino) tenere in memoria e reinviare ad
# ogni turno. Oltre questo numero, gli scambi più vecchi vengono scartati per
# non far crescere indefinitamente il costo in token di ogni richiesta.
MAX_SCAMBI_STORICO = 7


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
            if hasattr(res_emb, "values"):
                vector = res_emb.values
            elif isinstance(res_emb, list):
                vector = res_emb
            else:
                vector = list(res_emb)
            embeddings.append(vector)
        return embeddings

def avvia_chatbot():
    print("[INFO] Avvio assistente virtuale Nino...")
    
    client_genai = genai.Client(api_key=GEMINI_API_KEY)
    client_db = chromadb.PersistentClient(path=PERCORSO_DATABASE_VETTORIALE)
    
    if SCELTA_EMBEDDING == "google-001":
        embedding_func = GoogleGeminiEmbeddingFunction(api_key=GEMINI_API_KEY, model_name="models/gemini-embedding-001")
    elif SCELTA_EMBEDDING == "google-2":
        embedding_func = GoogleGeminiEmbeddingFunction(api_key=GEMINI_API_KEY, model_name="models/gemini-embedding-2")
    else:
        embedding_func = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="paraphrase-multilingual-mpnet-base-v2")
    
    try:
        collezione = client_db.get_collection(name=NOME_COLLEZIONE, embedding_function=embedding_func)
    except Exception as e:
        print(f"[ERRORE] Impossibile trovare la collezione ChromaDB: {e}. Esegui prima caricaprodotti.py")
        return

    # Gestiamo la history "a mano" (invece di chat.create) per poterla
    # troncare: l'SDK reinvia comunque l'intera conversazione ad ogni turno,
    # quindi teniamo solo gli ultimi MAX_SCAMBI_STORICO scambi per non far
    # crescere indefinitamente il costo in token di ogni richiesta.
    config_generazione = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT_NINO,
        temperature=0.3,
    )
    storico = []  # lista di types.Content (ruoli alternati "user"/"model")

    print("\n" + "="*70)
    print("🤖 NINO (SO FOOD) È ONLINE - Digita la tua richiesta o 'esci' per chiudere.")
    print("="*70)

    while True:
        user_query = input("\nTu: ").strip()
        if user_query.lower() in ["esci", "exit", "quit"]:
            print("Nino: A presto! Buon lavoro in cucina.")
            break
        if not user_query:
            continue

        risultati = collezione.query(
            query_texts=[user_query],
            n_results=N_RISULTATI_RAG
        )

        contesto_testuale = ""
        if risultati["ids"] and risultati["ids"][0]:
            for idx, (doc_id, meta, doc_text, dist) in enumerate(zip(
                risultati["ids"][0],
                risultati["metadatas"][0],
                risultati["documents"][0],
                risultati["distances"][0]
            )):
                contesto_testuale += f"\n--- PRODOTTO {idx+1} (ID: {doc_id}) ---\n"
                contesto_testuale += f"Fornitore: {meta.get('nome_fornitore')} | Categoria: {meta.get('categoria_prodotto')}\n"
                contesto_testuale += f"Varianti/Formati: {meta.get('varianti_prodotto')}\n"
                contesto_testuale += f"Scheda: {doc_text}\n"

        if not contesto_testuale:
            contesto_testuale = "Nessun prodotto direttamente corrispondente trovato nel database."

        prompt_finale = f"""
CONTEXT DAL CATALOGO SO FOOD:
{contesto_testuale}

RICHIESTA DEL CLIENTE:
{user_query}
"""

        # Tronchiamo lo storico PRIMA di aggiungere il turno corrente, così
        # manteniamo al massimo MAX_SCAMBI_STORICO scambi precedenti
        max_messaggi = MAX_SCAMBI_STORICO * 2  # ogni scambio = 1 user + 1 model
        if len(storico) > max_messaggi:
            storico[:] = storico[-max_messaggi:]

        storico.append(types.Content(role="user", parts=[types.Part(text=prompt_finale)]))

        try:
            response = client_genai.models.generate_content(
                model=MODELLO_GEMINI,
                contents=storico,
                config=config_generazione,
            )
            print(f"\nNino: {response.text}")
            storico.append(types.Content(role="model", parts=[types.Part(text=response.text)]))
        except Exception as e:
            print(f"\n[ERRORE]: {e}")
            # non salviamo il turno fallito nello storico
            storico.pop()

if __name__ == "__main__":
    avvia_chatbot()