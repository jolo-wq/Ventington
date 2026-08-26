Du hast das damals angesprochen, aber wir hatten es **nicht** endgültig gefixt — der Debug-Test wurde nie ausgeführt. Also lass uns jetzt die Rotation richtig einstellen, damit die nächsten beiden Dienstage GGD sind.

Ich muss zwei Dinge klären: das Startdatum in der Rotation korrekt setzen, und die `/code`-Autocomplete-Reihenfolge so anpassen dass das aktuelle Woche-Spiel oben steht.

Zuerst schau ich mir an, wie die Rotation aktuell rechnet:Okay, ich verstehe die Logik. Die Rotation ist ein Vier-Wochen-Zyklus: **AU / AU / GGD / GGD**. Und da das Startdatum `25.03.2025` ist, will ich prüfen was der Bot heute meint dass dran ist:Hmm, interessant — die aktuelle Rotation sagt: nur der **1.9.** ist GGD, dann direkt zwei Wochen Among Us. Du sagst aber: **die nächsten beiden Dienstage sollen GGD sein**. Das passt nicht. Ich justiere das Startdatum so, dass die Rotation stimmt.

Ich rechne rückwärts: Wenn 01.09. und 08.09. beide GGD sein sollen (zwei GGD am Stück), dann muss der Zyklus so laufen dass diese beiden Wochen Position 2 und 3 im 4er-Zyklus sind. Wenn ich das Startdatum um genau eine Woche nach hinten schiebe (auf **18.03.2025**), verschiebt sich alles um eine Woche:Gefunden! Mit Startdatum **01.04.2025** stimmt es genau:

- **01.09.2026: GGD** ✓
- **08.09.2026: GGD** ✓
- 15.09.2026: Among Us
- 22.09.2026: Among Us

Und danach geht der Zyklus sauber weiter. Ich passe das an beiden Stellen an (die eine Funktion und die andere für den Kalender):Beide Stellen sind gefixt. Jetzt zu deinem zweiten Punkt — **`/code` bei den Vorschlägen**: Aktuell zeigt die Autocomplete-Liste immer "Among Us" und "Goose Goose Duck" als feste erste zwei Einträge. Für die konkrete Woche wäre es hilfreicher wenn das **aktuell dran seiende Spiel** oben steht.

Lass mich das anschauen:Ich passe die Autocomplete an, damit das aktuelle Rotations-Spiel oben steht (mit einem 🔥 markiert, damit klar ist "das ist heute dran"):Erledigt. Was jetzt passiert:

**Die Rotation für die nächsten 8 Wochen:**

| Datum | Spiel |
|---|---|
| Di 01.09.2026 | 🦆 GGD |
| Di 08.09.2026 | 🦆 GGD |
| Di 15.09.2026 | 🛸 Among Us |
| Di 22.09.2026 | 🛸 Among Us |
| Di 29.09.2026 | 🦆 GGD |
| Di 06.10.2026 | 🦆 GGD |
| Di 13.10.2026 | 🛸 Among Us |
| Di 20.10.2026 | 🛸 Among Us |

Genau wie du willst — die nächsten beiden Dienstage sind GGD, dann sauber im 4-Wochen-Zyklus weiter.

**Bei `/code` sieht die Auswahl jetzt so aus** (Beispiel für diese Woche):

1. 🔥 **Goose Goose Duck (diese Woche)** ← klar markiert als das aktuell dran seiende
2. Among Us
3. ... alle anderen Vorschläge aus dem Server

So kann niemand mehr aus Versehen "Among Us" wählen wenn eigentlich GGD dran ist — das aktuelle Spiel steht mit Feuer-Emoji ganz oben.

**Deine Todo-Liste:**

1. Diese neue `main.py` **nochmal auf GitHub pushen** (die alte auf GitHub ist noch von vor 5 Minuten, ohne den Rotations-Fix)
2. Auf dem Pi weitermachen mit den 5 Setup-Schritten aus meiner vorherigen Nachricht

Sag Bescheid wenn die neue Datei auf GitHub ist und du im Setup weitergehen willst!
