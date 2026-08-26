import os
import re
import json
import datetime
import time
from pathlib import Path
import pandas as pd
import chromadb
from chromadb.utils import embedding_functions
from google import genai
from dotenv import load_dotenv

# Carica le variabili d'ambiente dal file .env
load_dotenv()

# ====================================================================
# CONFIGURAZIONE CHIAVE API
# ====================================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("ATTENZIONE: GEMINI_API_KEY non trovata. Controlla di aver creato correttamente il file .env")

# ====================================================================
# SELEZIONE DEL MODELLO DI EMBEDDING
# ====================================================================
# Scegli quale modello usare:
# - "google-001" : usa models/gemini-embedding-001
# - "google-2"   : usa models/gemini-embedding-2
# - "locale"     : usa sentence-transformers (paraphrase-multilingual-mpnet-base-v2)
SCELTA_EMBEDDING = "google-001" 

FOGLI_EXCEL_DA_IGNORARE = {"LEGENDA", "RIEPILOGO PER FORNITORE"}
DIMENSIONE_BLOCCO_INVIO = 200
NOME_FILE_LOG_ANOMALIE = "anomalies_log.json"
PATTERN_CARTELLA_FORNITORE = re.compile(r"^19\d{6}$")
PATTERN_CARTELLA_COLLASSATA = re.compile(r"^(19\d{6})[\\\\/](.+)$")

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

class CaricatoreCatalogoSofood:
    def __init__(self, cartella_radice: str, percorso_database_vettoriale: str = "./database_vettoriale", cartella_output_log: str = "."):
        self.root = Path(cartella_radice)
        self.chroma_db_path = Path(percorso_database_vettoriale)
        self.cartella_output_log = Path(cartella_output_log)

        self.fornitori_dict = {}
        self.nome_azienda_to_an_forn = {}
        self.varianti_dict = {}
        self.riassunto_dict = {}
        self.disclaimer_text = ""
        self.elenco_anomalie = []

        print(f"[INFO] Connessione a ChromaDB in corso (percorso: {self.chroma_db_path.resolve()})")
        self.client = chromadb.PersistentClient(path=str(self.chroma_db_path))

        if SCELTA_EMBEDDING == "google-001":
            model_name = "models/gemini-embedding-001"
            print(f"[INFO] Attivazione embedding Google: {model_name}")
            self.embedding_function = GoogleGeminiEmbeddingFunction(api_key=GEMINI_API_KEY, model_name=model_name)
        elif SCELTA_EMBEDDING == "google-2":
            model_name = "models/gemini-embedding-2"
            print(f"[INFO] Attivazione embedding Google: {model_name}")
            self.embedding_function = GoogleGeminiEmbeddingFunction(api_key=GEMINI_API_KEY, model_name=model_name)
        else:
            print("[INFO] Attivazione embedding locale: paraphrase-multilingual-mpnet-base-v2")
            self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="paraphrase-multilingual-mpnet-base-v2"
            )

        self.collezione = self.client.get_or_create_collection(
            name="catalogo_sofood",
            embedding_function=self.embedding_function
        )

    def _trova_colonna(self, tabella: "pd.DataFrame", nomi_possibili: list) -> "str | None":
        for nome_da_cercare in nomi_possibili:
            for colonna_reale in tabella.columns:
                if str(colonna_reale).strip().lower() == nome_da_cercare.strip().lower():
                    return colonna_reale
        return None

    def _varianti_normalizzazione_codice(self, codice: str) -> list:
        codice = codice.strip().upper()
        varianti = {codice}
        varianti.add(codice.replace("_", "."))
        varianti.add(codice.replace(".", "_"))
        varianti.add(codice.replace("__", "/"))
        varianti.add(codice.replace("/", "__"))
        return list(varianti)

    def _registra_anomalia(self, fornitore: str, prodotto: str, file: str, tipo_errore: str) -> None:
        self.elenco_anomalie.append({
            "supplier": fornitore if fornitore else "UNKNOWN",
            "product": prodotto if prodotto else "UNKNOWN",
            "file": file,
            "error_type": tipo_errore,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    def carica_file_globali(self) -> None:
        print("\n[FASE 1] Caricamento file di anagrafica globali...")

        percorso_disclaimer = self.root / "FINE SINGOLO PRODOTTO.txt"
        if percorso_disclaimer.exists():
            try:
                self.disclaimer_text = percorso_disclaimer.read_text(encoding="utf-8").strip()
            except Exception as errore:
                print(f"   [ATTENZIONE] Impossibile leggere il disclaimer globale: {errore}")

        percorso_fornitori = self.root / "fornitori.csv"
        if percorso_fornitori.exists():
            try:
                tabella_fornitori = pd.read_csv(percorso_fornitori, dtype=str)
                tabella_fornitori.columns = [str(colonna).strip() for colonna in tabella_fornitori.columns]
                colonna_id = self._trova_colonna(tabella_fornitori, ["an_forn", "id_fornitore", "codice", "fornitore"])
                colonna_nome = self._trova_colonna(tabella_fornitori, ["nome_azienda", "ragione_sociale", "nome", "fornitore_nome", "descrizione"])
                if not colonna_id:
                    colonna_id = tabella_fornitori.columns[0]
                if not colonna_nome:
                    colonna_nome = tabella_fornitori.columns[1] if len(tabella_fornitori.columns) > 1 else tabella_fornitori.columns[0]

                for _, riga in tabella_fornitori.iterrows():
                    codice = str(riga[colonna_id]).strip()
                    nome_azienda = str(riga[colonna_nome]).strip()
                    if codice and codice != "nan":
                        self.fornitori_dict[codice] = nome_azienda
                        self.nome_azienda_to_an_forn[nome_azienda.strip().upper()] = codice
                        for singolo_marchio in nome_azienda.split(" | "):
                            self.nome_azienda_to_an_forn[singolo_marchio.strip().upper()] = codice
                print(f"   [OK] Anagrafica fornitori caricata ({len(self.fornitori_dict)} record).")
            except Exception as errore:
                print(f"   [ERRORE] Impossibile caricare fornitori.csv: {errore}")

        percorso_varianti = self.root / "varianti_prodotto.csv"
        if percorso_varianti.exists():
            try:
                tabella_varianti = pd.read_csv(percorso_varianti, dtype=str)
                tabella_varianti.columns = [str(colonna).strip() for colonna in tabella_varianti.columns]
                colonna_forn = self._trova_colonna(tabella_varianti, ["an_forn", "codice_fornitore"])
                colonna_art = self._trova_colonna(tabella_varianti, ["ar_codart", "codice_articolo", "articolo", "id"])
                if not colonna_art:
                    colonna_art = tabella_varianti.columns[0]
                for _, riga in tabella_varianti.iterrows():
                    codice_prodotto = str(riga[colonna_art]).strip().upper()
                    codice_fornitore = str(riga[colonna_forn]).strip() if colonna_forn else ""
                    if codice_prodotto and codice_prodotto != "NAN":
                        varianti_trovate = []
                        for nome_colonna in tabella_varianti.columns:
                            if nome_colonna not in (colonna_art, colonna_forn) and pd.notna(riga[nome_colonna]):
                                valore_variante = str(riga[nome_colonna]).strip().upper()
                                if valore_variante and valore_variante != "NAN":
                                    varianti_trovate.append(valore_variante)
                        if varianti_trovate:
                            testo_varianti = ", ".join(varianti_trovate)
                            if codice_fornitore and codice_fornitore != "NAN":
                                chiave_composta = f"{codice_fornitore}|{codice_prodotto}"
                                self.varianti_dict[chiave_composta] = testo_varianti
                            self.varianti_dict[codice_prodotto] = testo_varianti
                print(f"   [OK] Varianti prodotto caricate ({len(self.varianti_dict)} chiavi indicizzate).")
            except Exception as errore:
                print(f"   [ATTENZIONE] Impossibile caricare varianti_prodotto.csv: {errore}")

        percorso_riassunto = self.root / "riassunto_prodotti.xlsx"
        if percorso_riassunto.exists():
            try:
                file_excel = pd.ExcelFile(percorso_riassunto)
                fogli_da_leggere = [
                    foglio for foglio in file_excel.sheet_names
                    if foglio.strip().upper() not in FOGLI_EXCEL_DA_IGNORARE
                ]
                for nome_foglio in fogli_da_leggere:
                    tabella_foglio = pd.read_excel(percorso_riassunto, sheet_name=nome_foglio, dtype=str)
                    tabella_foglio.columns = [str(colonna).strip() for colonna in tabella_foglio.columns]
                    colonna_prodotto = self._trova_colonna(tabella_foglio, ["codice prodotto", "ar_codart", "codice_articolo", "articolo", "codice"])
                    colonna_fornitore = self._trova_colonna(tabella_foglio, ["codice fornitore", "an_forn"])
                    colonna_nome_azienda = self._trova_colonna(tabella_foglio, ["nome azienda", "nome_azienda", "fornitore"])
                    colonna_allergeni = self._trova_colonna(tabella_foglio, ["allergeni", "allergene"])
                    colonna_tracce = self._trova_colonna(tabella_foglio, ["tracce di", "tracce_di", "tracce"])
                    colonna_biologico = self._trova_colonna(tabella_foglio, ["biologico", "bio"])
                    colonna_vegano = self._trova_colonna(tabella_foglio, ["vegano", "vegan"])
                    colonna_vegetariano = self._trova_colonna(tabella_foglio, ["vegetariano", "veg"])
                    colonna_senza_glutine = self._trova_colonna(tabella_foglio, ["senza glutine", "gluten free", "gluten_free"])
                    colonna_senza_lattosio = self._trova_colonna(tabella_foglio, ["senza lattosio", "lactose free", "lactose_free"])
                    colonna_milk_free = self._trova_colonna(tabella_foglio, ["milk free", "milk_free", "senza latte"])
                    colonna_kosher = self._trova_colonna(tabella_foglio, ["kosher"])
                    
                    if not colonna_prodotto:
                        colonna_prodotto = tabella_foglio.columns[2] if len(tabella_foglio.columns) > 2 else tabella_foglio.columns[0]

                    for _, riga in tabella_foglio.iterrows():
                        valore_grezzo = riga.get(colonna_prodotto)
                        if pd.notna(valore_grezzo):
                            codice_pulito = str(valore_grezzo).strip().upper()
                            codice_fornitore_riga = ""
                            if colonna_fornitore and pd.notna(riga.get(colonna_fornitore)):
                                codice_fornitore_riga = str(riga[colonna_fornitore]).strip()
                            elif colonna_nome_azienda and pd.notna(riga.get(colonna_nome_azienda)):
                                nome_azienda_riga = str(riga[colonna_nome_azienda]).strip().upper()
                                codice_fornitore_riga = self.nome_azienda_to_an_forn.get(nome_azienda_riga, "")
                            
                            dettagli = {
                                "categoria": nome_foglio,
                                "allergeni": str(riga.get(colonna_allergeni)).strip() if colonna_allergeni and pd.notna(riga.get(colonna_allergeni)) else "Non specificato",
                                "tracce_di": str(riga.get(colonna_tracce)).strip() if colonna_tracce and pd.notna(riga.get(colonna_tracce)) else "Nessuna",
                                "biologico": str(riga.get(colonna_biologico)).strip().upper() if colonna_biologico and pd.notna(riga.get(colonna_biologico)) else "NO",
                                "vegano": str(riga.get(colonna_vegano)).strip().upper() if colonna_vegano and pd.notna(riga.get(colonna_vegano)) else "NO",
                                "vegetariano": str(riga.get(colonna_vegetariano)).strip().upper() if colonna_vegetariano and pd.notna(riga.get(colonna_vegetariano)) else "NO",
                                "senza_glutine": str(riga.get(colonna_senza_glutine)).strip().upper() if colonna_senza_glutine and pd.notna(riga.get(colonna_senza_glutine)) else "NO",
                                "senza_lattosio": str(riga.get(colonna_senza_lattosio)).strip().upper() if colonna_senza_lattosio and pd.notna(riga.get(colonna_senza_lattosio)) else "NO",
                                "milk_free": str(riga.get(colonna_milk_free)).strip().upper() if colonna_milk_free and pd.notna(riga.get(colonna_milk_free)) else "NO",
                                "kosher": str(riga.get(colonna_kosher)).strip().upper() if colonna_kosher and pd.notna(riga.get(colonna_kosher)) else "NO",
                            }
                            for variante_codice in self._varianti_normalizzazione_codice(codice_pulito):
                                self.riassunto_dict[variante_codice] = dettagli
                                if codice_fornitore_riga:
                                    chiave_composta = f"{codice_fornitore_riga}|{variante_codice}"
                                    self.riassunto_dict[chiave_composta] = dettagli
                print(f"   [OK] Dettagli estesi caricati da Excel ({len(self.riassunto_dict)} chiavi).")
            except Exception as errore:
                print(f"   [ERRORE] Impossibile leggere riassunto_prodotti.xlsx: {errore}")

    def _cerca_dettagli_estesi(self, codice_fornitore: str, codice_prodotto: str) -> dict:
        codice_prodotto = codice_prodotto.strip().upper()
        varianti_codice = self._varianti_normalizzazione_codice(codice_prodotto)
        for variante in varianti_codice:
            chiave_composta = f"{codice_fornitore}|{variante}"
            if chiave_composta in self.riassunto_dict:
                return self.riassunto_dict[chiave_composta]
        for variante in varianti_codice:
            if variante in self.riassunto_dict:
                return self.riassunto_dict[variante]
        return {"categoria": "Non specificato", "allergeni": "Non specificato", "tracce_di": "Nessuna", "biologico": "NO", "vegano": "NO", "vegetariano": "NO", "senza_glutine": "NO", "senza_lattosio": "NO", "milk_free": "NO", "kosher": "NO"}

    def _cerca_varianti_prodotto(self, codice_fornitore: str, codice_prodotto: str) -> str:
        codice_prodotto = codice_prodotto.strip().upper()
        varianti_codice = self._varianti_normalizzazione_codice(codice_prodotto)
        for variante in varianti_codice:
            chiave_composta = f"{codice_fornitore}|{variante}"
            if chiave_composta in self.varianti_dict:
                return self.varianti_dict[chiave_composta]
        for variante in varianti_codice:
            if variante in self.varianti_dict:
                return self.varianti_dict[variante]
        return "Nessuna variante"

    def scansiona_e_carica(self) -> None:
        print("\n[FASE 2] Scansione dell'albero delle cartelle...")
        documenti_da_inserire = []
        metadati_da_inserire = []
        id_da_inserire = []
        contatore_letti = 0

        for cartella_livello1 in self.root.iterdir():
            if not cartella_livello1.is_dir():
                continue
            nome_cartella = cartella_livello1.name
            corrispondenza_collassata = PATTERN_CARTELLA_COLLASSATA.match(nome_cartella)
            if corrispondenza_collassata:
                codice_fornitore_estratto = corrispondenza_collassata.group(1)
                codice_prodotto_estratto = corrispondenza_collassata.group(2)
                nome_fornitore = self.fornitori_dict.get(codice_fornitore_estratto, "Fornitore Sconosciuto")
                self._elabora_singolo_prodotto(cartella_livello1, codice_fornitore_estratto, nome_fornitore, codice_prodotto_estratto, documenti_da_inserire, metadati_da_inserire, id_da_inserire)
                contatore_letti += 1
                continue

            if PATTERN_CARTELLA_FORNITORE.match(nome_cartella):
                an_forn = nome_cartella
                nome_fornitore = self.fornitori_dict.get(an_forn, "Fornitore Sconosciuto")
                for cartella_prodotto in cartella_livello1.iterdir():
                    if not cartella_prodotto.is_dir():
                        continue
                    self._elabora_singolo_prodotto(cartella_prodotto, an_forn, nome_fornitore, cartella_prodotto.name, documenti_da_inserire, metadati_da_inserire, id_da_inserire)
                    contatore_letti += 1
                continue

        print(f"\n[RIEPILOGO SCANSIONE] Prodotti validi trovati nei file: {contatore_letti}")
        self._scrivi_log_anomalie()

        if documenti_da_inserire:
            print(f"\n[FASE 3] Sincronizzazione incrementale con ChromaDB...")
            try:
                # 1. Recupero della collezione SENZA cancellarla
                self.collezione = self.client.get_or_create_collection(
                    name="catalogo_sofood", 
                    embedding_function=self.embedding_function
                )
                
                # 2. Rilevamento degli ID già indicizzati nel DB
                dati_esistenti = self.collezione.get()
                id_gia_salvati = set(dati_esistenti.get("ids", []))
                print(f"   [INFO] Prodotti già presenti nel database: {len(id_gia_salvati)}")

                nuovi_aggiunti = 0
                totale = len(documenti_da_inserire)

                # 3. Iterazione e caricamento solo dei record mancanti
                for idx in range(totale):
                    id_corrente = id_da_inserire[idx]
                    
                    if id_corrente in id_gia_salvati:
                        continue  # Salta all'istante il prodotto già indicizzato

                    self.collezione.add(
                        documents=[documenti_da_inserire[idx]],
                        metadatas=[metadati_da_inserire[idx]],
                        ids=[id_corrente],
                    )
                    nuovi_aggiunti += 1
                    print(f"   [OK] Indicizzato nuovo prodotto ({nuovi_aggiunti}): {id_corrente} [{idx+1}/{totale}]")
                    
                    if SCELTA_EMBEDDING in ["google-001", "google-2"]:
                        time.sleep(1.5)

                print(f"\n[SUCCESSO] Sincronizzazione completata. Nuovi prodotti aggiunti: {nuovi_aggiunti} (Totale nel DB: {len(id_gia_salvati) + nuovi_aggiunti}).")
            except Exception as errore:
                print(f"[ERRORE] Scrittura su ChromaDB fallita: {errore}")



    def _elabora_singolo_prodotto(self, cartella_prodotto: Path, an_forn: str, nome_fornitore: str, product_code: str, documenti_da_inserire: list, metadati_da_inserire: list, id_da_inserire: list) -> None:
        product_code_normalizzato = product_code.strip().upper()
        file_txt = cartella_prodotto / f"{product_code}.txt"
        file_jpg_principale = cartella_prodotto / f"{product_code}.jpg"
        file_pdf = cartella_prodotto / f"{product_code}.pdf"

        if not file_txt.exists():
            self._registra_anomalia(an_forn, product_code, f"{product_code}.txt", "NAMING_VIOLATION")
            return

        try:
            testo_prodotto = file_txt.read_text(encoding="utf-8").strip()
        except Exception:
            self._registra_anomalia(an_forn, product_code, file_txt.name, "NAMING_VIOLATION")
            return

        if not testo_prodotto:
            self._registra_anomalia(an_forn, product_code, file_txt.name, "INCOMPLETE_TEXT")
            return

        testo_finale = f"{testo_prodotto}\n\n[DISCLAIMER LEGALE SOFOOD]\n{self.disclaimer_text}" if self.disclaimer_text and self.disclaimer_text not in testo_prodotto else testo_prodotto

        varianti = self._cerca_varianti_prodotto(an_forn, product_code_normalizzato)
        dettagli_estesi = self._cerca_dettagli_estesi(an_forn, product_code_normalizzato)

        metadati = {
            "codice_prodotto": product_code,
            "codice_fornitore": an_forn,
            "nome_fornitore": nome_fornitore,
            "categoria_prodotto": dettagli_estesi["categoria"],
            "varianti_prodotto": varianti,
            "allergeni": dettagli_estesi["allergeni"],
            "tracce_di": dettagli_estesi["tracce_di"],
            "biologico": dettagli_estesi["biologico"],
            "vegano": dettagli_estesi["vegano"],
            "vegetariano": dettagli_estesi["vegetariano"],
            "senza_glutine": dettagli_estesi["senza_glutine"],
            "senza_lattosio": dettagli_estesi["senza_lattosio"],
            "milk_free": dettagli_estesi["milk_free"],
            "kosher": dettagli_estesi["kosher"],
            "ha_immagine_primaria": file_jpg_principale.exists(),
            "ha_pdf_tecnico": file_pdf.exists(),
            "percorso_cartella_locale": str(cartella_prodotto.resolve()),
        }

        id_vettore_univoco = f"{an_forn}_{product_code_normalizzato}"
        documenti_da_inserire.append(testo_finale)
        metadati_da_inserire.append(metadati)
        id_da_inserire.append(id_vettore_univoco)

    def _scrivi_log_anomalie(self) -> None:
        if not self.elenco_anomalie:
            return
        percorso_log = self.cartella_output_log / NOME_FILE_LOG_ANOMALIE
        anomalie_precedenti = []
        if percorso_log.exists():
            try:
                with open(percorso_log, "r", encoding="utf-8") as f:
                    anomalie_precedenti = json.load(f)
            except Exception:
                pass
        tutte = anomalie_precedenti + self.elenco_anomalie
        with open(percorso_log, "w", encoding="utf-8") as f:
            json.dump(tutte, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    CARTELLA_RADICE_CATALOGO = r"C:\Users\baron\LAVORO\PRODOTTI SOFOOD"
    PERCORSO_DATABASE_VETTORIALE = "./database_vettoriale"
    CARTELLA_LOG_ANOMALIE = "./log"

    if not Path(CARTELLA_RADICE_CATALOGO).exists():
        print(f"[ERRORE] La cartella '{CARTELLA_RADICE_CATALOGO}' non esiste.")
    else:
        caricatore = CaricatoreCatalogoSofood(CARTELLA_RADICE_CATALOGO, PERCORSO_DATABASE_VETTORIALE, CARTELLA_LOG_ANOMALIE)
        caricatore.carica_file_globali()
        caricatore.scansiona_e_carica()
        print("\n[FINE] Caricamento completato.")