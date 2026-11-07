# Errori e punti deboli della build 0.3 (Mac + OBS)

Analisi del codice sorgente, senza poterlo eseguire (serve un Mac). In ordine di gravità.

## Bug veri

1. **Blocco permanente dopo un crash.** Se l'app si chiude durante una registrazione resta il file `active.json`. Al riavvio l'app prova a fermare la sessione, ma se OBS è chiuso la connessione fallisce, l'errore si ripete ogni 2 secondi e il file non viene mai cancellato. Anche "Ferma e salva" fallisce allo stesso modo. Se ne esce solo cancellando a mano `active.json` (`App.swift`, `boot()` e `stop()`).
2. **Lo stop può essere ignorato.** `stop()` esce subito se l'app è "occupata" (`guard !busy`). Se il Mac va in sospensione mentre l'app sta parlando con OBS (controllo ogni 15 s, configurazione, avvio), la richiesta di stop si perde e OBS continua a registrare (`App.swift`, notifica `willSleep`).
3. **Lo stop può rifiutarsi di fermare.** Prima di fermare, l'app confronta la cartella di OBS con quella salvata come testo esatto (`dir == a.folder`). Basta una differenza di forma del percorso (barra finale, percorso normalizzato) e l'app non ferma più la registrazione, ritentando all'infinito.
4. **Spazio disco sottostimato.** Usa `systemFreeSize`, che su APFS non conta lo spazio liberabile. Può rifiutare di partire ("servono 3 GB") anche quando lo spazio c'è. Andrebbe usato `volumeAvailableCapacityForImportantUsage`.
5. **Schermo salvato per ID.** L'ID dello schermo su macOS può cambiare dopo un riavvio o ricollegando un monitor: la configurazione salvata smette di funzionare ("Schermo non disponibile"). Due monitor con lo stesso nome inoltre si confondono nel menu (`ForEach(... id: \.localizedName)`).
6. **Banner REC sbagliato su Teams con più schede.** L'estensione controlla che la registrazione riguardi proprio quella scheda solo per Meet; per Teams mostra REC su tutte le schede Teams aperte (`worker.js`, `ownKey`).
7. **Risposte HTTP tutte "OK".** Il piccolo server locale scrive `HTTP/1.1 403 OK`, `404 OK`: innocuo per Chrome ma scorretto. Inoltre programma un timer di chiusura a ogni pezzo di dati ricevuto (`Bridge.swift`).
8. **Versioni non allineate.** L'app è 0.3.0, l'estensione dichiara 0.2.0.

## Limiti di progetto (non bug, ma impediscono l'obiettivo)

- **Una sola traccia audio mista**: impossibile poi separare te dagli altri. È il motivo principale per ripartire.
- **Nessuna trascrizione.**
- **Rilevamento della call fragile**: si basa sul testo dei pulsanti di Meet/Teams ("Esci dalla chiamata", "Leave call") in poche lingue. Un cambio di interfaccia di Google o Microsoft, o un browser in tedesco, e non registra più.
- **Teams web non sempre riconosciuto**: serve un link riunione nell'indirizzo. Le chiamate avviate dall'interno di Teams (chat, 1:1) spesso non lo hanno e non vengono registrate.
- **Teams desktop, Zoom e Windows non supportati.**
- **Dipendenza da OBS**: installazione, permessi, WebSocket con password, profilo dedicato. Molti punti in cui può rompersi, e un software pesante solo per registrare.
- **File grandi**: 1080p a 30 fps, circa 1,65 GB all'ora per una call dove 5–10 fps bastano.
- **Registra tutto lo schermo**, notifiche comprese.
- Si registra da sola all'avvio del Mac senza chiederlo (`SMAppService.register()` a ogni avvio se non registrata).
