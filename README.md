# AI Tree Recorder per Windows e Mac

Registra le call (Zoom, Teams, Meet, qualsiasi app, browser o desktop), le trascrive in locale e capisce chi ha detto cosa. Alla fine di ogni call prepara un report e un **pacchetto pronto da dare a qualsiasi IA**. Nessun dato esce dal PC, a meno che tu non attivi l'invio a un'IA.

## Come funziona

- **Due tracce audio separate:** il tuo microfono ("Io") e l'audio del PC ("Loro"). Così si sa chi parla senza usare IA.
- **Avvio automatico:** Windows segnala quale app sta usando il microfono. Quando Zoom, Teams o il browser lo prendono parte la registrazione; quando lo rilasciano si ferma.
- **Video leggero:** schermo intero o solo la finestra della call, a bitrate variabile. Quando lo schermo è fermo pesa quasi niente. Usa la scheda video se c'è (NVIDIA, Intel, AMD), altrimenti la CPU.
- **Audio in Opus**, il codec fatto per la voce.
- **Trascrizione locale** con Whisper: modello grande su NVIDIA, modello leggero su CPU.

## Compatibilità

Il programma lo ricorda a ogni avvio.

| Piattaforma | Io / Loro | Persone distinte dentro "Loro" |
|---|---|---|
| Zoom | sì | sì, fino a 16 tracce col nome, con un file per persona: in Zoom attiva *Impostazioni → Registrazione → Registra un file audio separato per ogni partecipante* e avvia la registrazione locale di Zoom |
| Meet, Teams | sì | non ancora: l'audio degli altri arriva già mixato |
| Altre app | sì | no |

## Peso della registrazione

| Qualità | Video | Audio | Peso indicativo |
|---|---|---|---|
| `audio` | nessuno | Opus 24 kbps | ~30 MB/ora |
| `leggera` (default) | max 1280 px, 5 fps | Opus 24 kbps | ~60–150 MB/ora |
| `media` | max 1920 px, 10 fps | Opus 32 kbps | ~150–400 MB/ora |
| `alta` | nativo, 30 fps | Opus 64 kbps | ~0,5–1,2 GB/ora |

Il video a bitrate variabile pesa di più solo quando sullo schermo c'è movimento (condivisioni, video).

## Installazione su Windows

1. Installa **Python 3.11 o 3.12** da python.org (spunta "Add python.exe to PATH").
2. Installa **ffmpeg**: apri il Prompt dei comandi e lancia `winget install Gyan.FFmpeg`.
3. In questa cartella:

   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

4. Solo con scheda NVIDIA, per la trascrizione veloce: `pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"`. Se non lo fai, o la GPU non va, usa la CPU da solo.

Al primo uso viene scaricato il modello di trascrizione (circa 500 MB su CPU, 1,6 GB su NVIDIA).

## Uso

**Con l'interfaccia (consigliato):** doppio clic su `Avvia AI Tree Recorder.bat`. Si apre una finestra e compare un'icona vicino all'orologio: verde in attesa, rossa quando registra. Dalla finestra scegli qualità, cattura, lingua e il tuo nome, vedi i livelli Io/Loro, avvii o fermi a mano, e dall'elenco delle call apri video, report, trascrizione o "Apri in Claude/ChatGPT/Gemini". Chiudendo la finestra resta attivo vicino all'orologio; per uscire usa il menu dell'icona.

**Da riga di comando:**

```
.venv\Scripts\activate
python -m aitree devices        controlla microfono, uscita audio, encoder video
python -m aitree auto           resta in attesa e registra da solo ogni call
python -m aitree record         registra subito, Ctrl+C per fermare
```

Opzioni: `--qualita audio|leggera|media|alta`, `--cattura schermo|finestra`, `--lingua it|en|auto`.

Altri comandi:

```
python -m aitree finalize "CARTELLA"     rifà trascrizione e report di una call
python -m aitree zoom "CARTELLA"         ritrascrive con le tracce per persona di Zoom
python -m aitree llm "CARTELLA" --apri claude          apre Claude con il pacchetto negli appunti
python -m aitree llm "CARTELLA" --invia claude         riassunto via API in riassunto-ia.md
python -m aitree telefono "CARTELLA" --resta   trascrive le registrazioni dell'app Android
python -m aitree config                  crea e mostra il file di impostazioni
```

## Cosa trovi dopo ogni call

In `Video\AI-TREE Call\anno-mese\data_ora_App\`:

| File | Cosa contiene |
|---|---|
| `call.mp4` | video + tracce audio: Mix (quella che senti), Io, Loro e, con Zoom, una traccia per persona (fino a 16) col suo nome. In VLC le scegli da Audio → Traccia |
| `trascrizione.md` / `.srt` / `.json` | testo con chi parla e quando; l'SRT si apre come sottotitoli del video |
| `report.md` | chi ha parlato quanto, parole ricorrenti, domande fatte, intervento più lungo (calcolato senza IA) |
| `pacchetto-llm.md` | istruzioni + dati + trascrizione, da incollare o trascinare in Claude, ChatGPT, Gemini o altre |
| `riassunto-ia.md` | solo se hai attivato l'invio via API |
| `meta.json` | durata, app, qualità, encoder usato |

## IA: pacchetto, chat e API

- **Pacchetto:** sempre creato. Funziona con qualsiasi IA: lo trascini nella chat e ottieni riassunto, decisioni, azioni da fare e punti aperti.
- **Apri la chat da solo:** con `"open_chat": "claude"` (o `chatgpt`, `gemini`) a fine call il pacchetto finisce negli appunti e si apre il sito: Ctrl+V e Invio.
- **Completamente automatico:** con una chiave API (`"provider": "claude"`, `"api_key": "..."`, `"auto_send": true`) il riassunto arriva da solo in `riassunto-ia.md` ed eventualmente per email. Su Claude il default è `claude-opus-5-5`; per OpenAI e Gemini indica il modello in `"model"`. Installa il pacchetto del provider (`pip install anthropic`, `openai` o `google-genai`). Costo indicativo con Claude: pochi centesimi per un'ora di call.

Gli abbonamenti Claude Pro, ChatGPT Plus e Gemini Advanced non includono l'accesso API, e i loro siti non permettono a un programma di creare conversazioni al posto tuo. Per questo l'opzione "login" è la chat aperta con il pacchetto pronto; l'automazione completa passa dall'API.

## Mac (macOS 14 Sonoma o successivo)

Stesso programma, con tre differenze: l'audio degli altri arriva da un piccolo helper nativo (ScreenCaptureKit di Apple), il video usa l'encoder del chip Apple (VideoToolbox), e c'è solo la finestra senza icona nella barra dei menu.

**Installazione:**

1. Installa **Python 3.12 da python.org** (quello di python.org include l'interfaccia grafica).
2. Facoltativo ma consigliato: con Homebrew `brew install ffmpeg`. Senza, l'installazione usa un ffmpeg incluso.
3. Doppio clic su **`Installa su Mac.command`**. Se macOS lo blocca: tasto destro → Apri. Al primo giro può chiederti di installare gli strumenti da riga di comando di Apple: accetta e rilancia.
4. Apri **`Avvia AI Tree Recorder.command`**. macOS chiede i permessi **Microfono** e **Registrazione schermo e audio** per il Terminale: concedili in Impostazioni di Sistema → Privacy e sicurezza, poi chiudi e riapri.

Controllo rapido: `.venv/bin/python -m aitree devices` mostra microfono, encoder, app che usano il microfono e lo stato dei permessi.

**Limiti su Mac:** la cattura per finestra non è disponibile (registra lo schermo principale); niente accelerazione NVIDIA, la trascrizione usa la CPU (sui chip Apple è comunque veloce); il rilevamento automatico delle call richiede macOS 14.

## Impostazioni

`python -m aitree config` crea `%APPDATA%\AI-TREE\config.json`. Le voci principali:

```json
{
  "quality": "leggera",
  "capture": "schermo",
  "language": "it",
  "my_name": "Francesco",
  "phone_inbox": "",
  "keep_wav": false,
  "llm": { "provider": "", "api_key": "", "model": "", "auto_send": false, "open_chat": "claude" },
  "email": { "enabled": false, "smtp_host": "smtp.gmail.com", "smtp_port": 587,
             "username": "", "password": "", "to": [] }
}
```

## Cose da sapere

- Registra il microfono e l'uscita audio **predefiniti di Windows**. Se nella call usi altre cuffie, impostale come predefinite prima.
- Con le **cuffie** la separazione è quasi perfetta. Con le casse il microfono ricapta gli altri: il programma riconosce le frasi doppie e le toglie da "Io".
- Cattura **finestra**: registra solo la finestra della call. Se la riduci a icona il video si interrompe (l'audio continua). Alcune finestre accelerate dalla GPU possono risultare nere: in quel caso usa `schermo`.
- Sotto lo spazio minimo (2 GB) non parte; sotto 0,5 GB si ferma e salva.
- Su CPU un'ora di call si trascrive in circa 5–15 minuti, con NVIDIA in 1–2.
- Avvisa i partecipanti che stai registrando.
