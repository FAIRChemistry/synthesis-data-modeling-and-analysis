# Extraktionshinweise für Laborjournal-Exceldateien (Stand 2026-05-21)

Fachliche Regeln für die Umwandlung von Laborjournal-Exceldateien in strukturierte JSON-Dokumente.

## 1. Grundregeln

- Übernehme nur Inhalte, die wörtlich oder als Tabellenwert im Workbook stehen. Keine Ergänzung aus chemischem Allgemeinwissen, typischen Prozeduren oder Trainingsdaten.
- Bilder, Diagramme und reine Formatierung werden ignoriert.
- Fehlende optionale Werte → `null`. Berechnete Zellwerte dürfen übernommen werden.
- Deutsche Originalformulierungen aus der Vorschrift bleiben erhalten.
- Der Dateiname (`source_filename` bzw. `reaction_name_from_filename`) ist eine zusätzliche Kontextquelle: er nennt die Reaktion (z. B. „Reduktion Aminoester Ile zu Alkohol") und hilft, generische Substratnamen im Vorschrifttext (z. B. „Aminoester") dem richtigen Tabelleneintrag zuzuordnen.
- Bei Konflikt zwischen Tabelle und Vorschrifttext hat die aufbereitete Tabelle Vorrang — auch bei expliziten Wiederholungszahlen wie `(xN)`. Der Vorschrifttext bestimmt Reihenfolge und qualitative Schritte nur, soweit er der Tabelle nicht widerspricht.

## 2. Anti-Halluzinations-Regel (verbindlich)

- `_dropwise: true` nur, wenn `tropfenweise`, `dropwise`, `langsam zutropfen` o. Ä. wörtlich im Text steht.
- Sicherheits-/Vorsichtsformulierungen (`vorsichtig`, `langsam`, `unter Eiskühlung`, `unter starkem Rühren`) nur in `_comment`, wenn wörtlich im Quelltext.
- Mengen, Temperaturen, Zeiten und Wiederholungen niemals schätzen. Fehlt eine Menge: `_amount` weglassen, `_comment: "Menge nicht angegeben"`.
- Tabellenwerte gelten genau einer Verwendung. Wenn ein Stoff (z. B. MeOH) im Text mehrfach zugegeben wird, gehört die Tabellenmenge zur **ersten Nennung**, die später folgenden Zugaben sind ohne `_amount` zu modellieren (`_comment: "Menge nicht angegeben"`) — auch wenn der Stoff in der Edukt-Tabelle dieselbe Zeile teilt.

## 3. Mengenfelder aus den Tabellen

Edukt-Tabelle (`starting_material_table_rows`):
- `g` → `mass_g` (Feststoffe), nur übernehmen wenn vorhanden.
- `V mL` → `volume_mL` (Flüssigkeiten/Lösungen), nur übernehmen wenn vorhanden.
- Spalte `mL` (zweite mL-Spalte, Ansatz) wird ignoriert.
- Fehlende Spalte → entsprechendes Feld bleibt `null`.

Produkt-Tabelle (`product_table_rows`):
- `Laufmittel` → `eluent_system` (ausschließlich aus dieser Zelle; nie aus dem Fließtext oder `Purify._eluent` ableiten; fehlt sie → `null`).
- `Habitus` → `appearance`; `Rf` → `rf_value`; `Ausw. g` → `yield_g`; `Ausb. %` → `yield_percent`.
- **Produktzeile ohne `Ausw. g` und ohne `Ausb. %`** (z. B. nur Name „Misch", „ausgewogen", „Diast (?)") wird **nicht** als Produkt aufgenommen.

## 3a. Strukturidentifikatoren aus dem eingebetteten Reaktionsschema

- `embedded_reaction_structures` und `embedded_reaction_smiles` werden deterministisch aus der nativen ChemDraw-Zeichnung extrahiert. Die Werte `smiles`, `inchi` und `inchikey` sind bereits gegeben: niemals neu erzeugen, normalisieren oder aus einem Namen ableiten.
- Wenn die Vorverarbeitung ein vollständiges Identifier-Triplett bereits in einer Zeile von `starting_material_table_rows` oder `product_table_rows` abgelegt hat, übernimm es unverändert in die entsprechende Zeile von `starting_materials` bzw. `products`.
- Liegt ein Triplett nur in `embedded_reaction_structures` vor, übernimm es in eine Materialzeile nur, wenn Rolle im Schema (`reactant`/`product`) und der Workbook-Kontext die Zuordnung eindeutig machen. Bei einer einfachen Ein-Substrat→Ein-Produkt-Zeichnung entspricht dies dem dargestellten Substrat bzw. Produkt.
- Bei mehrdeutiger Zuordnung die Identifier in den Materialzeilen weglassen. Keine molare Masse, Dichte, Formel oder andere Eigenschaft aus SMILES/InChI berechnen; solche Anreicherungen gehören in ein nachgelagertes Verfahren.

## 4. Begriffe und Zuordnungen

- Edukte (`starting_materials`) umfassen Startmaterialien, Reagenzien, Basen, Katalysatoren, Lösungsmittel, Quench-Reagenzien, Hilfsstoffe.
- Ansatz-Volumen → `batch_volume_mL`.
- Produkte → isolierte Zielverbindungen und isolierte Nebenprodukte von Interesse.
- Herkunftsangaben → `reagent_sources`; Einträge in der Literaturzeile gehören auch dorthin, wenn sie zu Edukten passen.

## 5. Generische Substratnamen ↔ Tabelleneinträge (verbindlich)

Vorschrifttexte verwenden oft generische Substantive statt der Tabellennamen: `Aminosäure`, `Aminosäureester`, `Aminoester`, `Aminoaldehyd`, `Aminoalkohol`, `Alkohol`, `Olefin`, `Fluorid`, `Edukt`, `Substrat`. Diese sind als Verweis auf das limitierende Edukt der Tabelle zu interpretieren (in der Regel die erste Edukt-Zeile bzw. die mit `eq = 1`). Auch der Dateiname hilft zur Disambiguierung.

**Folge für `procedure`:** Wenn der Text sagt „Aminoester … in THF lösen", muss ein `Add`-Schritt mit `_reagent` = exaktem Tabellennamen (z. B. `"Aminoester 065"`) erscheinen. Der generische Begriff darf nicht stillschweigend übergangen werden, sondern ist auf den Tabellennamen abzubilden.

## 6. Klammer-Konventionen im Tabellennamen

| Schreibweise in `starting_material_table_rows` | Bedeutung |
|---|---|
| `Reagenz (xN)` (z. B. `NaBH4 (x2)`, `NaBH4 (x3)`) | Reagenz wird **N-mal** zugegeben. Pro Zugabe ein eigener `Add`-Schritt; bei Wartezeit zwischen den Zugaben `Wait`-Schritt dazwischen. `note: "N-mal zugegeben"`. `(xN)` bestimmt die Anzahl exakt — niemals zu wenig oder zu viel. |
| `Lösungsmittel (Stoff)` (z. B. `THF (LAH)`, `DCM (NsCl)`, `DEE (FeCl3)`, `H2O (Fe(III)ox)`, `AcN (Selectfluor/Olefin)`, `H2O (quenchen)`) | Lösungsmittel ist **speziell** für den/die genannten Stoff(e) bzw. Schritt. `note` erläutert den Bezug. Bei mehreren Stoffen in Klammern (Slash-getrennt) bezieht sich das Volumen pro genanntem Stoff einmal — siehe §7. |

## 7. „X in Y" / „X-Lsg in Y" / `Y (X)` — Lösungsmittelzugabe vor Reagenz (verbindlich)

Immer wenn der Vorschrifttext eine Wendung der Form *„X in Y zugeben/lösen/versetzen"* oder *„X-Lsg (… in Y)"* enthält, oder wenn in `starting_materials` eine Zeile `Y (X)` existiert, muss in der `procedure` **zuerst** ein `Add Y` und **danach** ein `Add X` stehen — zwei separate Schritte. Das gilt unter anderem für:

- `Aminosäure/Aminoester/Aminoalkohol/Aminoaldehyd/Olefin in MeOH/DCM/THF/DEE/AcN lösen` → `Add` Solvens, dann `Add` Substrat.
- `LAH in THF` (Zeile `THF (LAH)`) → `Add THF` + `Add LAH`.
- `2-NsCl in DCM` (Zeile `DCM (NsCl)`) → `Add DCM` + `Add 2-NsCl`.
- `FeCl3 (1 M in DEE)` (Zeile `DEE (FeCl3)`) → `Add DEE` + `Add FeCl3`.
- `Fe(III)oxalat in Wasser` (Zeile `H2O (Fe(III)ox)`) → `Add H2O` + `Add Fe(III)oxalat` (+ ggf. `Wait`, falls Auflösezeit im Text).
- `Selectfluor … mit AcN`, `Olefin in Acetonitril` (Zeile `AcN (Selectfluor/Olefin)`) → AcN wird **pro Bezugsstoff einmal** zugegeben: `Add AcN`, `Add Selectfluor`, später erneut `Add AcN`, `Add Olefin`. Zwei AcN-Schritte sind Pflicht.

Die Menge des Lösungsmittels stammt aus der `V mL`-Spalte der zugehörigen `Y (X)`-Zeile, die Menge des Reagenz aus dessen eigener Zeile. Steht weder Menge im Text noch in der Tabelle: `_amount` weglassen + `_comment: "Menge nicht angegeben"`.

**Auch ohne dedizierte `Y (X)`-Zeile gilt die Wendung „X in Y" als verbindlich:** Wenn die Vorschrift z. B. „LAH in THF tropfenweise versetzen" sagt, der `THF`-Eintrag in der Tabelle aber nur einmal (für die Hauptlösung) existiert, ist trotzdem ein zusätzlicher `Add Y` direkt vor dem `Add X` einzufügen — `_amount` weglassen, `_comment: "Menge nicht angegeben"`. Die schon in Prep verwendete Tabellenmenge wird **nicht** dupliziert.

**Zeilen `Stoff (purpose)` wie `H2O (quenchen)` sind Mengen-Quelle für den so bezeichneten Schritt.** Der eingeklammerte Zweck nennt den Workup-/Reaction-Schritt, dem das Volumen direkt zugewiesen wird:
- `H2O (quenchen) V mL = 0.62` → der `Add Wasser`-Quench-Schritt in `Workup` bekommt `_amount: 0.62 mL`, **nicht** `Menge nicht angegeben`.
- `THF (LAH)` → Volumen geht in den `Add THF` direkt vor `Add LAH` in `Reaction`.

## 8. Temperatur-Bedingungen (verbindlich)

Jede Temperaturangabe im Vorschrifttext wird als eigener `HeatChill`-Schritt aufgenommen — auch ohne Verb wie „kühlen"/„erwärmen", wenn die Temperatur nur Begleitbedingung ist.

- „auf 0 °C / -20 °C kühlen", „auf RT erwärmen", „auf RT kommen lassen" → `HeatChill` auf den genannten Wert (RT = 25 °C).
- „bei 0 °C / -20 °C / RT [versetzen / zugeben / rühren / lösen]" → `HeatChill` auf den genannten Wert **direkt vor** dem qualifizierten Schritt.
- Auch wenn ein vorheriger `HeatChill` bereits eine andere Temperatur eingestellt hat, ist der Wechsel auf RT zwingend als eigener `HeatChill 25 °C` zu setzen, bevor die Reaktion bei RT weiterläuft (z. B. „… und Rühren für 48 h bei RT" nach Eiskühlung → vorher `HeatChill 25 °C`, dann `Wait 48 h`).
- `_time` nur, wenn explizit im Text genannt.

## 9. Abschnitte der `procedure`

| Abschnitt | Inhalt |
|---|---|
| `Prep` | Schutzgas, Vorlegen des Lösungsmittels, Lösen des limitierenden Edukts, Starttemperatur. Reine Vorbereitung. |
| `Reaction` | **Alle** Reagenzien-Zugaben (und deren dedizierte Lösungsmittel), Reaktionstemperatur, Reaktionszeit. |
| `Workup` | Quenchen, Extraktion, Waschen, Trocknen, Verdampfen, Reinigung. Beginn häufig mit „Aufarbeitung:". |

**Section-Grenze (verbindlich):** Sobald das erste Reagenz (z. B. Selectfluor, NaBH4, LAH, FeCl3, 2-NsCl, Thionylchlorid, DMP) zugegeben wird, beginnt `Reaction`. Auch wenn der Vorschrifttext vorher „Entgasen", „auf 0 °C kühlen" oder „bei RT" angibt — diese Begleitschritte gehören in `Prep`, das Reagenz selbst **nicht**. Ebenso gehört das Lösungsmittel, das ein Reagenz begleitet (`AcN (Selectfluor/Olefin)`, `THF (LAH)`, `DCM (NsCl)`, `DEE (FeCl3)`), zu seinem Reagenz in `Reaction`, **nicht** in `Prep`.

## 10. Schritt-Typen

| `$xml_type` | Pflichtfelder | Optionale Felder | Einsatz |
|---|---|---|---|
| `Add` | `_reagent`, `_amount` (optional siehe §2) | `_dropwise`, `_degassed`, `_repeat`, `_repeat_interval`, `_comment` | Zugabe; auch Quench |
| `HeatChill` | `_temp` | `_time`, `_comment` | Temperaturänderung/-haltung; `_time` nur explizit |
| `EvacuateAndRefill` | `_gas` | `_time`, `_comment` | Schutzgas / Entgasen — bei „entgasen" im Text **immer** `_comment: "Entgasen"` (zur Abgrenzung von reiner Schutzgasatmosphäre) |
| `Extract` | `_solvent` | `_repeat`, `_phase_kept`, `_comment` | Flüssig-flüssig-Extraktion |
| `WashPhase` | `_solution` | `_phase`, `_repeat`, `_comment` | Waschen einer Flüssigphase |
| `Wait` | `_time` | `_comment` | Warten/Rühren ohne Temperaturänderung |
| `Dry` | — | `_desiccant`, `_time`, `_temp`, `_pressure`, `_comment` | Trocknen mit Trockenmittel; **nicht** für Lösungsmittelentfernung |
| `Evaporate` | — | `_method`, `_temp`, `_pressure`, `_comment` | Lösungsmittel entfernen (Roti, Vakuum, N2-Strom) |
| `Purify` | `_eluent` | `_stationary_phase`, `_comment` | Säulenchromatographie; `_eluent` aus dem Fließtext; **`eluent_system` am Produkt nie hieraus ableiten** |
| `Sonicate` | `_time` | `_comment` | Ultraschall |

## 11. `Extract` — `_phase_kept` (verbindlich)

Standard: `_phase_kept: "organic"`. Bei organischen Extraktionslösungsmitteln (DCM, DEE, EtOAc/EE, CHCl3, MTBE, PE, Toluol etc.) wird die organische Phase aufbewahrt — **auch** wenn die Vorschrift formuliert „**wässrige Phase mit DEE/DCM extrahieren**" (Rück-Extraktion: das Lösungsmittel zieht das Produkt aus der wässrigen in die organische Phase, also bleibt die organische Phase). Nur explizite Hinweise wie „wässrige Phase aufbewahren/behalten/sammeln" setzen `_phase_kept: "aqueous"`.

## 12. Zuordnung typischer Formulierungen

| Formulierung im Text | `$xml_type` | Hinweis |
|---|---|---|
| „unter N2 lösen", „Schutzgas" | `EvacuateAndRefill` | `_gas: "N2"`; ohne `_comment: "Entgasen"` |
| „entgasen (X min)", „Entgasen" | `EvacuateAndRefill` | `_gas: "N2"`, `_time` aus Klammer falls vorhanden, `_comment: "Entgasen"` |
| „X (entgast)", „X (zuvor entgast)" | `Add` | `_degassed: true`; **kein** `EvacuateAndRefill` (der gilt nur dem Gefäß). Bei „X in Y (entgast)" gehört der Zusatz zum Lösungsmittel **Y** (§7), nicht zu X. Gilt für **jede** Zugabe von Y, die der Text so nennt. |
| „X in Y lösen/zugeben/versetzen" | `Add` (Y) + `Add` (X) | Siehe §7 |
| „X-Lsg (1 M in Y)" | `Add` (Y) + `Add` (X) | Siehe §7 |
| „tropfenweise zugeben" | `Add` | `_dropwise: true` |
| „erneut mit selber Menge"/„(xN)" | `Add` × N | N exakt aus `(xN)`; bei Wartezeit `Wait` dazwischen |
| „bei X °C [versetzen/rühren/...]" | `HeatChill` vor der Aktion | §8 |
| „rühren für X min/h" (ohne T-Wechsel) | `Wait` | `_time` direkt |
| „rühren ü.N." / „über Nacht" | `HeatChill` oder `Wait` | Dauer nur wenn explizit genannt |
| „auf RT erwärmen / kommen lassen" | `HeatChill` 25 °C | §8 |
| „quenchen mit Y" | `Add` | `_dropwise` nur bei wörtlichem „tropfenweise"; Menge nur wenn im Text/Tabelle |
| „mit Y versetzen, Phasen trennen", „mit Y extrahieren" | `Extract` | `_solvent: Y`; `_phase_kept` nach §11 |
| „mit DCM/MeOH 9:1 extrahieren" | `Extract` | `_solvent: "DCM/MeOH 9:1"` |
| „org. Phase mit Y waschen (n×)" | `WashPhase` | `_solution: Y`, `_phase: "organic"`, `_repeat: n` |
| „mit brine waschen" | `WashPhase` | `_solution: "brine"`, `_phase: "organic"` |
| „mit HCl (1M) waschen" | `WashPhase` | `_solution: "HCl 1M"` |
| „trocknen über MgSO4, abfiltrieren" | `Dry` | `_desiccant: "MgSO4"` |
| „LM am Roti entfernen", „einengen" | `Evaporate` | `_method: "rotary_evaporator"` |
| „LM entfernen (Wasserstrahlpumpe)" | `Evaporate` | `_method: "vacuum"` |
| „Säule (Pe/EtOAc ...)" | `Purify` | `_eluent` exakt aus Text inkl. Gradient |

## 13. `_comment`-Nutzung

`_comment` nur, wenn der Schritt-Typ allein nicht alle Information trägt und der Inhalt aus dem Quelltext belegbar ist. Zulässig insbesondere: wörtliche Sonderbedingungen („OHNE zusätzliches Wasser"), `"Menge nicht angegeben"`, `"Dauer nicht angegeben"`, `"Entgasen"`. Keine Sicherheitshinweise aus Allgemeinwissen.

## 14. Abkürzungen und Synonyme

Alle Schreibweisen werden auf den kanonischen Namen normalisiert (linke Spalte):

| Kanonisch | Synonyme |
|---|---|
| `Acetonitril` | AcN, MeCN |
| `Dichlormethan` | DCM, CH2Cl2 |
| `Ethylacetat` | EtOAc, EA, EE |
| `Methanol` | MeOH |
| `Ethanol` | EtOH |
| `Dimethylsulfoxid` | DMSO |
| `Tetrahydrofuran` | THF |
| `Diethylether` | Et2O, DEE |
| `Wasser` | H2O |
| `Petrolether` | PE |
| `Eisen(III)-oxalat-Hexahydrat` | Fe(III)ox, Fe(III)oxalat x 6 H2O |

Zeit-/Temperatur-/Begriffsabkürzungen:

| Kanonisch | Synonyme | Schema-Wert |
|---|---|---|
| `min` | Min., mins, Minuten | `Unit: "minute"` |
| `h` | hr, hrs, Stunden | `Unit: "hour"` |
| `equivalents` | eq, Eq., equiv, equiv., Äquiv. | numerisch |
| `Raumtemperatur` | rt, RT, r.t. | `_temp: { Value: 25, Unit: "celsius" }` |
| `konzentriert` | konz., konz | — |
| `gesättigt` | sat., sat | — |
| `über Nacht` | ü.N., üN, overnight | nur explizite Dauer übernehmen |
| `Roti` / Rotationsverdampfer | — | `Evaporate { _method: "rotary_evaporator" }` |
| `0 °C` (Eisbad) | — | `_temp: { Value: 0, Unit: "celsius" }` |

## 15. Negativbeispiele (häufige Fehler)

- **Quench ohne Tropfenangabe:** Text „quenchen mit Wasser" → `Add Wasser` ohne `_dropwise`, ohne „vorsichtig". Falsch wäre `_dropwise: true` aus chemischem Vorwissen.
- **Eluent vom Produkt:** `_eluent` im `Purify` und `eluent_system` am Produkt sind getrennte Quellen. Fehlt die Spalte „Laufmittel" in der Produktzeile, ist `eluent_system: null` — auch wenn das Eluent im Text steht.
- **Mehrfache Lösungsmittelnutzung:** MeOH (V mL = 150) in der Tabelle, Text nennt MeOH in Prep **und** in Workup → Tabellenmenge nur in der ersten Verwendung. Zweite Verwendung: kein `_amount`, `_comment: "Menge nicht angegeben"`.
- **Rück-Extraktion:** „wässrige Phase mit DEE extrahieren" → `Extract { _solvent: "DEE", _phase_kept: "organic" }`. Nicht `aqueous`.
- **Generischer Substratname:** Text sagt nur „Aminoester", Tabelle hat „Aminoester 065" → `Add`-Schritt mit `_reagent: "Aminoester 065"`.
- **`(xN)`-Zähler:** Reagenz `NaBH4 (x3)` → drei separate `Add`-Schritte, nicht zwei.
- **„Entgasen" vs. „Schutzgas":** Text „Entgasen (10 min)" → `EvacuateAndRefill` mit `_time` und `_comment: "Entgasen"`; reines „unter N2" ohne dieses Wort → ohne Kommentar.
