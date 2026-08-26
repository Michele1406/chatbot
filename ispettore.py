import chromadb

client = chromadb.PersistentClient(path="./database_vettoriale")
try:
    collezione = client.get_collection("catalogo_sofood")
    dati = collezione.get()
    
    print(f"Totale prodotti indicizzati finora: {len(dati.get('ids', []))}")
    
    fornitori_conteggio = {}
    for meta in dati.get("metadatas", []):
        nome_supp = meta.get('nome_fornitore', 'Sconosciuto')
        cod_supp = meta.get('codice_fornitore', 'Sconosciuto')
        chiave = f"{cod_supp} - {nome_supp}"
        fornitori_conteggio[chiave] = fornitori_conteggio.get(chiave, 0) + 1
        
    print("\nRiepilogo per fornitore:")
    for supp, count in sorted(fornitori_conteggio.items(), key=lambda x: x[1], reverse=True):
        print(f"   - {supp}: {count} prodotti")
except Exception as e:
    print(f"Errore nella lettura del DB: {e}")
    