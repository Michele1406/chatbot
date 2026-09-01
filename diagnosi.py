"""
DIAGNOSI COPERTURA DB VETTORIALE - SO FOOD
============================================================
Script diagnostico, VELOCE e GRATUITO (nessuna chiamata a Gemini): confronta
i codici presenti nel database vettoriale con TUTTE le righe dell'Excel
(non solo "DA ASSEGNARE"), per capire dove si sovrappongono davvero le tue
schede prodotto.

Serve a rispondere alla domanda: "ho 1076 schede, perche' ne matchano solo
~215 tra le righe da assegnare?" - il sospetto e' che la maggior parte delle
tue schede riguardi prodotti GIA' classificati bene (confidenza alta/media),
non la coda lunga ancora da assegnare.

USO
    python diagnosi_copertura_db.py

Va lanciato nella cartella del progetto "chatbot" (dove sta ./database_vettoriale),
con l'Excel (originale o quello con le correzioni gia' scritte) nella stessa cartella.
"""

from pathlib import Path
import pandas as pd
import chromadb

# ====================================================================
PERCORSO_EXCEL = "tassonomia-prodotti-da-validare.xlsx"  # o il file con le correzioni gia' scritte
PERCORSO_DATABASE_VETTORIALE = "./database_vettoriale"
NOME_COLLEZIONE = "catalogo_sofood"
# ====================================================================


def normalizza(testo) -> str:
    return str(testo).strip().upper() if testo is not None else ""


def varianti_codice(codice: str) -> set:
    """Stessa logica di _varianti_normalizzazione_codice in caricaprodotti.py:
    gestisce i codici con '/' convertiti in '__' per compatibilita' cartelle."""
    codice = normalizza(codice)
    varianti = {codice}
    varianti.add(codice.replace("_", "."))
    varianti.add(codice.replace(".", "_"))
    varianti.add(codice.replace("__", "/"))
    varianti.add(codice.replace("/", "__"))
    return varianti


def main():
    client = chromadb.PersistentClient(path=PERCORSO_DATABASE_VETTORIALE)
    collezione = client.get_collection(name=NOME_COLLEZIONE)
    dati = collezione.get()

    codici_db = set()
    fornitori_per_codice = {}
    for metadati in dati["metadatas"]:
        codice_grezzo = metadati.get("codice_prodotto")
        if codice_grezzo:
            for variante in varianti_codice(codice_grezzo):
                codici_db.add(variante)
                fornitori_per_codice.setdefault(variante, set()).add(metadati.get("nome_fornitore", ""))

    print(f"[INFO] Codici distinti nel DB vettoriale: {len({normalizza(m.get('codice_prodotto')) for m in dati['metadatas'] if m.get('codice_prodotto')})}")
    print(f"[INFO] Schede totali (righe embeddings):   {len(dati['ids'])}")

    df = pd.read_excel(PERCORSO_EXCEL, sheet_name="Prodotti da validare")
    df["CODICE_NORM"] = df["CODICE"].apply(normalizza)
    df["IN_DB"] = df["CODICE"].apply(lambda c: bool(varianti_codice(c) & codici_db))

    print(f"\n[INFO] Righe totali in Excel: {len(df)}")
    print(f"[INFO] Di cui presenti nel DB (per codice): {df['IN_DB'].sum()}")

    print("\n" + "=" * 70)
    print("SOVRAPPOSIZIONE DB <-> EXCEL, PER FASCIA DI CONFIDENZA")
    print("=" * 70)
    riepilogo = df.groupby("CONFIDENZA")["IN_DB"].agg(["sum", "count"])
    riepilogo.columns = ["presenti_nel_db", "totale_righe"]
    riepilogo["percentuale_coperta"] = (riepilogo["presenti_nel_db"] / riepilogo["totale_righe"] * 100).round(1)
    print(riepilogo.to_string())

    print("\n" + "=" * 70)
    print("SOVRAPPOSIZIONE DB <-> EXCEL, PER 'IN CATALOGO'")
    print("=" * 70)
    riepilogo2 = df.groupby("IN CATALOGO", dropna=False)["IN_DB"].agg(["sum", "count"])
    riepilogo2.columns = ["presenti_nel_db", "totale_righe"]
    print(riepilogo2.to_string())

    # I codici del DB che NON esistono da nessuna parte nell'Excel (confrontando
    # anche le varianti): utile per scoprire refusi di battitura nel nome del
    # codice o prodotti ormai fuori listino.
    codici_excel_con_varianti = set()
    for codice in df["CODICE"]:
        codici_excel_con_varianti |= varianti_codice(codice)
    codici_db_orfani = {normalizza(m.get("codice_prodotto")) for m in dati["metadatas"] if m.get("codice_prodotto")} - codici_excel_con_varianti
    print(f"\n[INFO] Codici nel DB che NON compaiono in nessuna riga dell'Excel: {len(codici_db_orfani)}")
    if codici_db_orfani:
        esempio = sorted(list(codici_db_orfani))[:15]
        print("        Esempio (primi 15, ordine alfabetico):")
        for codice in esempio:
            print(f"          - {codice}  (fornitore: {', '.join(fornitori_per_codice.get(codice, []))})")

    # Salva su file l'elenco completo dei codici DA ASSEGNARE / non classificato
    # ancora SENZA scheda nel DB, cosi' hai la lista precisa da scrivere.
    mask_da_scrivere = df["CONFIDENZA"].isin(["DA ASSEGNARE", "non classificato"]) & (~df["IN_DB"])
    colonne_export = ["CODICE", "DESCRIZIONE", "FORNITORE", "CONFIDENZA", "IN CATALOGO", "VENDUTO 12M"]
    df.loc[mask_da_scrivere, colonne_export].sort_values("VENDUTO 12M", ascending=False).to_csv(
        "codici_senza_scheda_da_scrivere.csv", index=False
    )
    print(f"\n[OK] Elenco dei {mask_da_scrivere.sum()} codici DA ASSEGNARE/non classificato SENZA scheda "
          f"salvato in: codici_senza_scheda_da_scrivere.csv (ordinato per fatturato)")


if __name__ == "__main__":
    main()