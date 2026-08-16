# IMPAROMA

Un'app web **mobile-first** (PWA) per allenare la sezione **Leggere** della certificazione **PLIDA B1**.
Tutta l'interfaccia utente è in **italiano**; il codice sorgente è in inglese.

## Stack

- **Backend:** FastAPI + Uvicorn
- **Templates:** Jinja2 + [htmx](https://htmx.org/) (vendored, offline-friendly)
- **CSS:** design system custom, mobile-first (niente build step)
- **DB:** SQLite (stdlib `sqlite3`, WAL)
- **PWA:** `manifest.json` + service worker (cache shell offline)
- **IA:** Gemini Flash (`gemini-3.5-flash-lite`) via REST API, chiave in `.env`

## Funzionalità

- **📚 Allenamento** — le 4 parti dell'esame con gli esercizi reali del PLIDA B1 Leggere:
  - *Parte 1* — 38 testi brevi con scelta multipla (A/B/C/D) e feedback immediato
  - *Parte 2* — 11 esercizi di abbinamento profili ↔ annunci (A–G), profili scorrevoli
  - *Parte 3* — 9 esercizi di completamento del testo con lacune numerate e bottom sheet
  - *Parte 4* — 9 esercizi di notizie ↔ titoli di giornale (A–I)
- **Percorso a sblocchi (stile videogioco)**: per passare all'esercizio successivo devi
  rispondere correttamente a tutte le domande dell'esercizio corrente. Quando finisci tutti
  gli esercizi reali di una parte, compare un esercizio **✨ Generato con IA**; superandolo
  se ne genera subito un altro, all'infinito. Gli esercizi IA sono stilisticamente simili
  all'esame reale (esempi reali nel prompt + validazione del formato).
- **⏱️ Simulazione** — scegli tra **Solo esercizi reali**, **Reale + IA** o **Tutto IA**
  (le modalità con IA richiedono `GEMINI_API_KEY`). Esame a tempo (40 minuti) con punteggio finale.
- **📖 Vocabolario** — salva le parole chiave da ripassare + **riepilogo IA** dei progressi
- **🔍 Spiegazione** — feedback immediato con spiegazione in italiano
- **💡 Parole Chiave** — glossario integrato dei termini B1 difficili
- **↺ Ricomincia da zero** — azzera tentativi e sfide IA generate (mantiene il vocabolario)
- **👤 Profilo & account** — login con telefono + password, un dispositivo alla volta,
  badge profilo nell'intestazione e pannello amministrazione per creare/gestire gli utenti

> **Fonte degli esercizi**: i dati in `data/exercises/*.json` sono la trascrizione fedele dei
> fascicoli reali del PLIDA B1 Leggere (Prima, Seconda, Terza e Quarta Parte) contenuti nella
> cartella `test-pdf/`. Le risposte della Prima Parte non erano indicate nei fascicoli e sono
> state derivate dai testi (da verificare con la chiave ufficiale se disponibile).

## Quick start

```bash
cd ~/Documents/italian-test
chmod +x run.sh
./run.sh
```

Apri <http://127.0.0.1:8050>.

## Configurazione (`.env`)

Copia `.env.example` in `.env` e imposta:

| Variabile | Default | Descrizione |
|---|---|---|
| `ADMIN_PHONE` / `ADMIN_PASSWORD` | `+584126778168` / *(obbligatoria)* | Al primo avvio creano l'account amministratore (numero + password). Se la password è vuota, l'account admin NON viene creato. |
| `ADMIN_NAME` | `Amministratore` | Nome dell'account admin. |
| `SESSION_COOKIE_SECURE` | `false` | Metti `true` se l'app è servita via HTTPS (consigliato). |
| `GEMINI_API_KEY` | *(vuoto)* | Chiave Google AI per il generatore. Se vuota, le sfide IA non appaiono dopo aver completato una parte. |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Modello Gemini usato per la generazione. |
| `ITALIAN_TEST_HOST` / `ITALIAN_TEST_PORT` | `127.0.0.1` / `8050` | Bind del server. |
| `ITALIAN_TEST_DB` | `data/italian_test.db` | Percorso del database SQLite. |

## Account e dispositivi

- Gli utenti vengono creati **solo dall'amministratore** nel pannello `/admin`
  (l'account admin è creato al primo avvio da `ADMIN_PHONE`/`ADMIN_PASSWORD`).
- Login con **numero di telefono + password**: il campo telefono ha un selettore
  del prefisso internazionale (predefinito 🇻🇪 +58) nel login e nel pannello admin.
- Ogni profilo è legato a **un solo dispositivo** alla volta: se è già connesso
  altrove, il login su un secondo dispositivo viene rifiutato. L'amministratore
  può disconnettere un dispositivo da remoto (o lo fai tu uscendo dall'app).

## Docker

```bash
GEMINI_API_KEY=tuo_valore docker compose up --build
```

## Struttura

```
italian-test/
├── app/
│   ├── main.py        # Rotte FastAPI (pagine + grading + IA + vocabolario)
│   ├── config.py      # Impostazioni da .env
│   ├── models.py      # Pydantic v2
│   ├── database.py    # SQLite (vocabolario, tentativi)
│   ├── exercises.py   # Caricamento esercizi seed
│   ├── grading.py     # Verifica delle risposte
│   └── gemini.py      # Client Gemini Flash
├── data/exercises/    # p1.json … p4.json (esercizi reali PLIDA B1)
├── test-pdf/          # Fascicoli originali (Prima–Quarta Parte)
├── templates/         # Pagine + partials htmx
├── static/            # CSS, JS, htmx, manifest, icone, service worker
├── requirements.txt
├── run.sh
├── Dockerfile
└── docker-compose.yml
```

## API principali

| Metodo | Rota | Descrizione |
|---|---|---|
| GET | `/` | Reindirizza ad `/login` o `/practice` |
| GET/POST | `/login` | Accesso con telefono + password |
| POST | `/logout` | Esci dall'account |
| GET | `/profile` | Profilo utente |
| GET | `/admin` | Pannello amministrazione (solo admin) |
| GET | `/practice` / `/practice/{part}` | Elenco parti / esercizi |
| GET | `/exercise/{id}` | Pagina esercizio |
| GET | `/simulation` | Selettore modalità (reale / reale+IA / tutto IA) |
| GET | `/simulation/{mode}` | Simulazione a tempo per la modalità scelta |
| POST | `/progress/reset` | Azzera progressi e sfide IA |
| POST | `/ai/report` | Riepilogo IA dei progressi |
| GET | `/vocab` | Vocabolario |
| POST | `/answer`, `/verify/{part}` | Grading (htmx partial) |
| POST | `/simulation/grade` | Consegna simulazione |
| GET | `/api/health` | Liveness |

## Note

- I seed (`data/exercises/*.json`) coprono tutte e 4 le parti in italiano, livello B1.
- Il generatore IA produce JSON validato con Pydantic nello stesso schema dei seed.
- L'app funziona completamente offline dopo il primo caricamento (shell cache).
