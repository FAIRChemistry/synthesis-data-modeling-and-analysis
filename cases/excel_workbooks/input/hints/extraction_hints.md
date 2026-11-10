# Extraktionshinweise für Laborjournal-Exceldateien

Diese Datei enthält fachliche Regeln und Interpretationshilfen für die Umwandlung von Laborjournal-Exceldateien in strukturierte JSON-Dokumente.

## Allgemeine Grundregeln

- Alle expliziten Informationen aus dem Excel sollen übernommen werden, sofern sie zum Schema passen.
- Bilder, Diagramme und reine Formatierung werden ignoriert.
- Leere Felder sollen nicht erfunden werden. Wenn ein optionaler Wert fehlt, soll `null` verwendet werden.
- Deutsche Fachbegriffe und Originalformulierungen aus der Vorschrift sollen erhalten bleiben.
- Tabellenwerte haben Vorrang vor ausformulierten Annahmen.
- Berechnete Werte aus Excel dürfen übernommen werden, wenn sie als Zellwert vorhanden sind.
- Wenn eine Angabe nur aus dem Kontext erschlossen wird, soll sie konservativ interpretiert werden.

## Anti-Halluzinations-Regel (verbindlich)

Es darf **nichts** aus chemischem Allgemeinwissen, aus typischen Prozeduren oder aus Trainingsdaten ergänzt werden. Übernommen werden ausschließlich Inhalte, die wörtlich oder als Tabellenwert in der Excel-Datei stehen.

Das gilt insbesondere für **Schritt-Modifikatoren** in der `procedure` und für **Freitext in `_comment`**:

- `_dropwise: true` darf **nur** gesetzt werden, wenn im Vorschrifttext wörtlich `tropfenweise`, `dropwise`, `langsam zutropfen` o. Ä. steht.
- Worte wie `vorsichtig`, `sehr vorsichtig`, `langsam`, `unter Eiskühlung`, `unter starkem Rühren` o. Ä. dürfen **nur** dann in `_comment` erscheinen, wenn sie wörtlich im Quelltext stehen.
- Reaktionstypisches Vorwissen (z. B. „LAH-Quench mit Wasser ist konventionell tropfenweise") ist **keine** zulässige Quelle. Wenn der Text nur `quenchen mit Wasser` sagt, dann ist die Zugabe ein einfacher `Add`-Schritt **ohne** `_dropwise` und **ohne** Sicherheitskommentar.
- Mengen, Temperaturen, Zeiten und Wiederholungen dürfen nie geschätzt oder aus typischen Werten ergänzt werden. Fehlt eine Menge, wird `_amount` weggelassen und in `_comment` `"Menge nicht angegeben"` vermerkt — nichts darüber hinaus.

**Negativbeispiel (Ch-066-Typ):** Vorschrift sagt nur `quenchen mit Wasser`. Falsch wäre `{ "$xml_type": "Add", "_reagent": "Wasser", "_dropwise": true, "_comment": "tropfenweise und sehr vorsichtig" }`. Richtig ist `{ "$xml_type": "Add", "_reagent": "Wasser", "_comment": "Menge nicht angegeben" }` — ohne `_dropwise`, ohne „vorsichtig".

## Mengen: `mass_g` vs. `volume_mL`

In der aufbereiteten Edukt-Tabelle (`starting_material_table_rows`) sind die Spalten eindeutig benannt:

- **`"g"` (Spalte "g")** → `mass_g`. Dieser Wert steht für Feststoffe (Pulver, Salze). Nur übernehmen, wenn das Feld in der Tabelle vorhanden ist.
- **`"V mL"` (Spalte "V mL")** → `volume_mL`. Dieser Wert steht für Flüssigkeiten und Lösungen. Nur übernehmen, wenn das Feld in der Tabelle vorhanden ist.
- Die Spalte **`"mL"`** (zweite mL-Spalte, enthält Ansatz-Wert) gehört **nicht** in `volume_mL` — sie wird ignoriert.
- Wenn eine Spalte in der Tabelle nicht vorhanden ist, bleibt das entsprechende Feld `null`.

In der aufbereiteten Produkt-Tabelle (`product_table_rows`):

- **`"Laufmittel"`** → `eluent_system`. Nur übernehmen, wenn dieses Feld in der Produkt-Zeile vorhanden ist. Fehlt es, bleibt `eluent_system: null`.
- **`"Habitus"`** → `appearance`
- **`"Rf"`** → `rf_value`
- **`"Ausw. g"`** → `yield_g`
- **`"Ausb. %"`** → `yield_percent`

## Wichtige Begriffe

### Edukte

Edukte umfassen nicht nur Startmaterialien, sondern auch Reagenzien, Basen, Katalysatoren, Lösungsmittel, Quench-Reagenzien und Hilfsstoffe.

**Für JSON beachten:** Alle diese Einträge gehören grundsätzlich in `starting_materials`.

### Ansatz

Der Ansatz ist das Gesamtvolumen der Reaktion in mL.

**Für JSON beachten:** Dieser Wert gehört in `batch_volume_mL`.

### Produkte

Produkte sind isolierte Zielverbindungen oder isolierte Nebenprodukte von Interesse.

**Für JSON beachten:** Meist gibt es ein Hauptprodukt, manchmal zusätzlich ein zweites relevantes Produkt.

### Herkunft der Edukte

Dieser Bereich beschreibt Lagerort, Quelle oder Provenienz der eingesetzten Stoffe.

**Für JSON beachten:** Diese Angaben gehören in `reagent_sources`.

## Regeln für Kommentare und Klammern

### Kommentar `(x2)`

**Wenn im Excel steht:** Ein Edukt oder Reagenz enthält `(x2)`, z. B. `NaBH4 (x2)`.

**Dann bedeutet das:** Die Zugabe oder der betreffende Schritt erfolgt zweimal.

**Für JSON beachten:** Der Stoffname darf den Hinweis enthalten. Zusätzlich soll `note` sinngemäß gesetzt werden, z. B. `zweimal zugegeben`.

### Klammern bei Lösungsmitteln

**Wenn im Excel steht:** Ein Lösungsmittel enthält Edukte in Klammern, z. B. `AcN (Selectfluor/Olefin)`.

**Dann bedeutet das:** Das Lösungsmittel wird für die genannten Stoffe verwendet. Die angegebene Menge kann sich auf diese Edukte bzw. Lösungen beziehen.

**Für JSON beachten:** Das Lösungsmittel bleibt ein eigener Eintrag in `starting_materials`. Die Klammerinformation soll zusätzlich in `note` erklärt werden.

Wenn ein Lösungsmittel mit Klammerbezug angegeben ist, z. B. `AcN (Selectfluor/Olefin)`, bezieht sich ein angegebenes Volumen auf jeden genannten Stoff einzeln.

**Für JSON beachten:** Das Volumen muss für jeden referenzierten Stoff separat übernommen werden. Es darf nicht aufgeteilt oder nur einmal verwendet werden.

### Lösungsmittel mit Stoffbezug

Wenn ein Lösungsmittel mit einem Stoff in Klammern angegeben ist, z. B. `H2O (Fe(III)ox)`, bedeutet dies, dass dieses Lösungsmittel speziell für diesen Stoff verwendet wird.

**Für JSON beachten:** Der Bezug soll in `note` festgehalten werden. Das Lösungsmittel bleibt ein eigener Eintrag.

**Für die procedure — Stoff in Lösungsmittel geben (z. B. `H2O (Fe(III)ox)`):**

Wenn die Vorschrift sagt „X in Wasser geben" oder „X in Lösungsmittel lösen", müssen **zwei separate `Add`-Schritte** angelegt werden — nicht nur einer:

1. `Add` **Wasser** (oder das Lösungsmittel), Menge aus der Zeile `H2O (Fe(III)ox)` in `starting_materials` (`V mL`-Spalte).
2. `Add` **Fe(III)oxalat x 6 H2O** (oder den Stoff), Menge aus der `g`-Spalte in `starting_materials`.
3. Falls ein Auflöse-/Rühr-Zeit im Text steht (z. B. „für 2 h rühren, bis vollst. gelöst"), danach ein `Wait`-Schritt mit `_time: { "Value": 2, "Unit": "hour" }`.

**Für die procedure mit `AcN (Selectfluor/Olefin)`:**

Das Lösungsmittel AcN wird laut Vorschrift zweimal zugegeben — je einmal für Selectfluor und einmal für Olefin. Es müssen **zwei separate `Add`-Schritte** für AcN in der `procedure` stehen:

1. `Add` **AcN**, Menge = Volumen aus der AcN-Zeile in `starting_materials`, unmittelbar **vor oder zusammen mit** dem Selectfluor-Schritt. Dann `Add` **Selectfluor**.
2. `Add` **AcN** (erneut, gleiche Menge), unmittelbar **vor oder zusammen mit** dem Olefin-Schritt. Dann `Add` **Olefin**.

Wenn der Text z. B. sagt *„mit Selectfluor und AcN versetzen"*: erst AcN, dann Selectfluor.  
Wenn der Text sagt *„Olefin in Acetonitril zugeben"*: erst AcN (zweiter Schritt), dann Olefin.

## Temperatur-Bedingungen (verbindlich)

Jede Temperaturangabe im Vorschrifttext muss als eigener `HeatChill`-Schritt in die `procedure` aufgenommen werden — auch dann, wenn der Text **kein** Verb wie „kühlen" oder „erwärmen" verwendet, sondern die Temperatur nur als Begleitbedingung nennt.

Maßgebliche Formulierungen (nicht abschließend):

- „auf 0 °C kühlen" / „auf -20 °C kühlen" → `HeatChill` mit dem genannten Wert.
- „bei 0 °C / -20 °C / RT [versetzen / zugeben / rühren / lösen]" → `HeatChill` auf den genannten Wert **direkt vor** dem so qualifizierten Schritt. RT wird als `25 °C` modelliert.
- „auf RT erwärmen" / „auf RT kommen lassen" → `HeatChill` auf `25 °C`.

Bei Texten der Form „bei X mit Y versetzen" muss in der `procedure` zuerst ein `HeatChill`-Schritt mit `_temp = X` stehen und danach der zugehörige `Add`-Schritt. Auch wenn ein vorheriger HeatChill-Schritt eine andere Temperatur eingestellt hat (z. B. -20 °C im Prep) und der nächste Abschnitt „bei RT" weiterarbeitet, ist der RT-Schritt zwingend zu setzen — sonst geht die Temperaturänderung verloren.

**Positivbeispiel (Ch-132-Typ).** Vorschrift: „Entgasen (10 min) und bei RT mit Selectfluor und AcN versetzen. Anschließend Olefin in Acetonitril zugeben, ..., Rühren für 30 min bei 0 °C". Erwartete `Reaction.Step`-Folge:

1. `HeatChill` `_temp: { "Value": 25, "Unit": "celsius" }` (für „bei RT").
2. `Add` AcN, `Add` Selectfluor, `Add` AcN, `Add` Olefin, `Add` NaBH4, `Wait`, `Add` NaBH4.
3. `HeatChill` `_temp: { "Value": 0, "Unit": "celsius" }`, `_time: { "Value": 30, "Unit": "minute" }` (für „Rühren für 30 min bei 0 °C").

**Negativbeispiel.** Wenn der erste HeatChill-Schritt zu RT fehlt, gilt der Ablauf als unvollständig — die RT-Bedingung ist die zentrale Variation gegenüber dem Standardansatz und darf nicht stillschweigend wegfallen.

## Regeln für Arbeitsschritte

### Extraktion

**Wenn in der Vorschrift steht:** `extrahieren`, `Phasen trennen`, `org. Phase`, `wässrige Phase`, `waschen` oder Ähnliches.

**Dann bedeutet das:** Es werden zwei nicht mischbare Phasen verwendet, meist eine wässrige und eine organische. Stoffe werden durch Mischen und anschließendes Trennen zwischen ihnen verteilt.

**Typischer Ablauf:**

1. Stoff oder Lösung zugeben.
2. Phasen mischen.
3. Phasen trennen.
4. Gewünschte Phase behalten.
5. Schritt ggf. mehrfach wiederholen.

**Für JSON beachten:** Die genaue Vorschrift soll als Text erhalten bleiben. Wiederholungen wie `(2x)` oder `(3x)` dürfen nicht verloren gehen.

**Für das strukturierte Schema zusätzlich beachten:** Im `procedure`-Objekt als `Extract`-Schritt modellieren. Das Extraktionslösungsmittel gehört in `_solvent`; eine explizite Wiederholung soll in `_repeat` oder, falls nötig, im `_comment` erhalten bleiben.

**Wichtig — `Extract` vs. `Add`:** `Extract` ist nur zu verwenden, wenn der Text **explizit** eine Phasentrennung beschreibt (z. B. „Phasen trennen", „extrahieren", „org. Phase abnehmen"). Wird ein Lösungsmittel lediglich zugegeben, ohne dass Phasen getrennt werden, ist stattdessen `Add` zu verwenden.

### Waschen einer Phase

**Wenn in der Vorschrift steht:** `mit Wasser waschen`, `mit brine waschen`, `mit HCl waschen` oder Ähnliches.

**Dann bedeutet das:** Eine Phase, meist die organische, wird mit einer anderen Phase in Kontakt gebracht, um Verunreinigungen zu entfernen.

**Für JSON beachten:** Dies gehört zur `procedure`. Die Waschlösung kann als Reagenz/Edukt aufgenommen werden, wenn sie in der Edukt-Tabelle steht oder mengenmäßig angegeben ist.

**Für das strukturierte Schema zusätzlich beachten:** Im Workup als `WashPhase`-Schritt modellieren: `_solution` = Name der Waschlösung (Freitext), `_phase: "organic"`, `_repeat` für Anzahl der Wäschen. Die Extraktion selbst (Lösungsmittel + Phasentrennung) als `Extract` modellieren.

### Trocknen

**Wenn in der Vorschrift steht:** `trocknen über MgSO4`, `trocknen über Magnesiumsulfat` oder ähnliche Formulierungen.

**Dann bedeutet das:** Restwasser wird aus einer Lösung entfernt. Dazu wird ein Trockenmittel zugegeben, gemischt und anschließend abfiltriert.

**Typischer Ablauf:**

1. Trockenmittel zugeben, z. B. Magnesiumsulfat.
2. Vermengen oder stehen lassen.
3. Feststoff abfiltrieren.
4. Wasserfreie Lösung weiterverwenden.

**Für JSON beachten:** Dieser Schritt gehört zur `procedure`. Steht das Trockenmittel in der Edukt-Tabelle, soll es auch in `starting_materials` aufgenommen werden.

**Für das strukturierte Schema zusätzlich beachten:** Als `Dry`-Schritt im Workup modellieren; `trocknen über MgSO4, abfiltrieren` kann bei Bedarf im `_comment` erhalten bleiben.

### Verdampfen

**Wenn in der Vorschrift steht:** `LM entfernen`, `am Roti entfernen`, `einengen`, `verdampfen` oder ähnliche Formulierungen.

**Dann bedeutet das:** Lösungsmittel wird entfernt, meist am Rotationsverdampfer.

**Für JSON beachten:** Dieser Schritt gehört zur `procedure`. Er führt meist zu Rohprodukt oder weiter zu reinigendem Material.

**Für das strukturierte Schema zusätzlich beachten:** Als `Evaporate`-Schritt modellieren; bei typischer Entfernung am Roti `_method: "rotary_evaporator"` setzen.

### Säulenchromatographie / Säule

**Wenn in der Vorschrift steht:** `Säule`, `säulen`, `Chromatographie`, `PE/EE`, `Pe/EtOAc` oder ähnliche Formulierungen.

**Dann bedeutet das:** Es handelt sich um eine größere Trenn- bzw. Filtrationsmethode zur Reinigung des Rohprodukts. Dabei entstehen mehrere Fraktionen, von denen relevante vereinigt werden.

**Für JSON beachten:**

- Der Schritt gehört zur `procedure`.
- Das Laufmittel aus dem Fließtext der Vorschrift gehört in `_eluent` des `Purify`-Schritts.
- Das Feld `eluent_system` beim Produkt darf **ausschließlich** aus dem Zellwert der Produkttabelle (Spalte „Laufmittel" in `product_table_rows`) übernommen werden, **nicht** aus dem Fließtext der Vorschrift, **nicht** aus dem `_eluent` des `Purify`-Schritts, und **nicht** durch Ableitung oder Spiegelung. Steht in der Produkt-Tabellenzeile keine Spalte „Laufmittel", bleibt `eluent_system` zwingend `null`.
- **Negativbeispiel (Ch-066-Typ):** Die Vorschrift enthält „Säule (Pe/EtOAc 4:1 -> 3:1 -> 1:1)" und die Produktzeile hat **keine** Spalte „Laufmittel". Korrekt: `_eluent` des `Purify`-Schritts = `"Pe/EtOAc 4:1 -> 3:1 -> 1:1"`, **aber** `eluent_system` am Produkt = `null`. Das ist kein Versehen, sondern beabsichtigt: Wenn das Eluent nicht in der Produkttabellenzelle steht, gilt es als nicht in der Produkttabelle dokumentiert.
- Wenn mehrere Laufmittelverhältnisse angegeben sind, sollen sie als Text erhalten bleiben, z. B. `Pe/EtOAc 4:1 -> 3:1 -> 1:1`.

**Für das strukturierte Schema zusätzlich beachten:** Als `Purify`-Schritt im Workup modellieren; `_eluent` enthält das Laufmittelsystem als Freitext, inklusive Gradient.

### Zweites Verdampfen nach Reinigung

**Wenn nach einer Säule erneut Lösungsmittel entfernt wird:** Dadurch wird das endgültige Produkt aus den vereinigten Fraktionen erhalten.

**Für JSON beachten:** Dies gehört zur `procedure`. Die isolierte Masse gehört beim Produkt in `yield_g`.

**Für das strukturierte Schema zusätzlich beachten:** Falls der Lösungsmittelentzug als eigener Aufarbeitungsschritt modelliert wird, als weiterer `Evaporate`-Schritt erfassen.

### Entgasen

**Wenn in der Vorschrift steht:** `entgasen`, `mit Stickstoff entgasen`, `N2 durchleiten`, `unter Stickstoff spülen` oder ähnliche Formulierungen.

**Dann bedeutet das:** Durch das angegebene Lösungsmittel oder die Reaktionslösung wird Stickstoff geleitet, um gelöste Gase zu entfernen oder eine inerte Atmosphäre herzustellen.

**Typischer Ablauf:**

1. Lösungsmittel oder Reaktionslösung bereitstellen.
2. Stickstoff einleiten.
3. Für die angegebene Zeit durchleiten.
4. Optional unter Stickstoffatmosphäre weiterarbeiten.

**Für JSON beachten:** Die genaue Vorschrift soll als Text erhalten bleiben. Ist eine Dauer angegeben, z. B. in Klammern, soll sie übernommen werden. Fehlt sie, darf keine Zeit ergänzt oder angenommen werden.

**Zusätzlich beachten:** Wiederholungen wie `(2x)` oder `(3x)` müssen genau übernommen werden. Es darf weder eine zusätzliche noch eine implizite Wiederholung ergänzt werden.

**Für das strukturierte Schema zusätzlich beachten:** Als `EvacuateAndRefill`-Schritt modellieren. `_gas` soll auf `N2` gesetzt werden, wenn Stickstoff genannt ist. Wenn eine Dauer angegeben ist, soll sie in `_time` übernommen werden; wenn keine Dauer angegeben ist, bleibt `_time` leer.

## Regeln für Produktzustand und Reinheit

### Rohprodukt

**Wenn die Vorschrift auf Rohprodukt hinweist:** Das Zielprodukt ist vor der Reinigung meist noch durch Nebenprodukte, Reagenzien oder Lösungsmittel verunreinigt.

**Für JSON beachten:** Die endgültigen Produktdaten sollen aus der Produkttabelle entnommen werden, nicht aus einer bloßen Rohprodukt-Erwähnung.

### Habitus

**Wenn in der Produkttabelle ein Habitus angegeben ist:** Dies beschreibt Aussehen oder Aggregatzustand, z. B. Feststoff, Öl, Farbe.

**Für JSON beachten:** Der Wert gehört in `appearance`.

## Regeln für leere oder verschobene Bereiche

### Leere Literatur

**Wenn `Literatur:` vorhanden ist, aber leer ist:** Es soll keine Literaturangabe erfunden werden.

**Für JSON beachten:** Literatur wird im aktuellen Schema nicht benötigt und kann ignoriert werden, wenn der Bereich leer ist.

### Verschobene Herkunftseinträge

**Wenn ein Herkunftseintrag optisch in derselben Zeile wie `Literatur:` steht:** Das kann ein Layout-Artefakt sein.

**Dann bedeutet das:** Der Eintrag kann trotzdem zur Herkunft der Edukte gehören.

**Für JSON beachten:** Wenn der Stoffname zu einem Edukt passt, soll er in `reagent_sources` übernommen werden.

## Beispiele für typische Interpretationen

### Beispiel: `NaBH4 (x2)`

**Interpretation:** Natriumborhydrid wird zweimal eingesetzt bzw. zweimal zugegeben.

**JSON-Hinweis:** `note` sollte eine Erklärung wie `zweimal zugegeben` enthalten.

### Beispiel: `AcN (Selectfluor/Olefin)`

**Interpretation:** Acetonitril ist das Lösungsmittel für Selectfluor und Olefin.

**JSON-Hinweis:** `role` ist wahrscheinlich `solvent`; die Klammerinformation gehört in `note`.

### Beispiel: `Mit DCM/MeOH 9:1 extrahieren`

**Interpretation:** Extraktion mit einem organischen Lösungsmittelgemisch.

**JSON-Hinweis:** Die Formulierung soll in der `procedure` erhalten bleiben.

### Beispiel: `Säule (PE/EE 4:1)`

**Interpretation:** Reinigung per Säulenchromatographie mit Petroleumether/Ethylacetat im Verhältnis 4:1.

**JSON-Hinweis:** `_eluent` des `Purify`-Schritts ist `PE/EE 4:1`. Das Feld `eluent_system` beim Produkt wird nur dann auf `PE/EE 4:1` gesetzt, wenn dieser Wert explizit in der Produkttabellen-Zelle steht.

## Abkürzungen und Synonyme

### Acetonitril

Acetonitril kann in Vorschriften z. B. als `AcN`, `MeCN` oder ausgeschrieben als `Acetonitril` bezeichnet werden.

**Für JSON beachten:** Alle diese Bezeichnungen meinen denselben Stoff und müssen einheitlich als `Acetonitril` erfasst werden. Unterschiedliche Schreibweisen dürfen nicht als separate Einträge behandelt werden.

---

### Dichlormethan

Dichlormethan kann als `DCM`, `CH2Cl2` oder ausgeschrieben als `Dichlormethan` bezeichnet werden.

**Für JSON beachten:** Alle diese Bezeichnungen müssen einheitlich als `Dichlormethan` erfasst werden.

---

### Ethylacetat

Ethylacetat kann als `EtOAc`, `EA`, `EE` oder ausgeschrieben als `Ethylacetat` bezeichnet werden.

**Für JSON beachten:** Alle diese Bezeichnungen müssen einheitlich als `Ethylacetat` erfasst werden.

---

### Methanol

Methanol kann als `MeOH` oder ausgeschrieben als `Methanol` bezeichnet werden.

**Für JSON beachten:** Alle diese Bezeichnungen müssen einheitlich als `Methanol` erfasst werden.

---

### Ethanol

Ethanol kann als `EtOH` oder ausgeschrieben als `Ethanol` bezeichnet werden.

**Für JSON beachten:** Alle diese Bezeichnungen müssen einheitlich als `Ethanol` erfasst werden.

---

### Dimethylsulfoxid

Dimethylsulfoxid kann als `DMSO` oder ausgeschrieben als `Dimethylsulfoxid` bezeichnet werden.

**Für JSON beachten:** Alle diese Bezeichnungen müssen einheitlich als `Dimethylsulfoxid` erfasst werden.

---

### Tetrahydrofuran

Tetrahydrofuran kann als `THF` oder ausgeschrieben als `Tetrahydrofuran` bezeichnet werden.

**Für JSON beachten:** Alle diese Bezeichnungen müssen einheitlich als `Tetrahydrofuran` erfasst werden.

---

### Diethylether

Diethylether kann als `Et2O` oder ausgeschrieben als `Diethylether` bezeichnet werden.

**Für JSON beachten:** Alle diese Bezeichnungen müssen einheitlich als `Diethylether` erfasst werden.

---

### Wasser

Wasser kann als `H2O` oder ausgeschrieben als `Wasser` bezeichnet werden.

**Für JSON beachten:** Alle diese Bezeichnungen müssen einheitlich als `Wasser` erfasst werden.

---

### Petrolether

Petrolether kann als `PE` oder ausgeschrieben als `Petrolether` bezeichnet werden.

**Für JSON beachten:** Alle diese Bezeichnungen müssen einheitlich als `Petrolether` erfasst werden.

---

### Eisen(III)-oxalat-Hexahydrat

Eisen(III)-oxalat-Hexahydrat kann als `Fe(III)ox` oder ausgeschrieben als `Fe(III)oxalat x 6 H2O` bezeichnet werden.

**Für JSON beachten:** Alle diese Bezeichnungen müssen einheitlich als `Eisen(III)-oxalat-Hexahydrat` erfasst werden.

---

### Raumtemperatur

Raumtemperatur kann als `rt`, `RT`, `r.t.` oder ausgeschrieben als `Raumtemperatur` bezeichnet werden.

**Für JSON beachten:** Alle diese Bezeichnungen müssen einheitlich als `Raumtemperatur` erfasst werden. Unterschiedliche Schreibweisen dürfen nicht als separate Bedingungen interpretiert werden.

---

### Äquivalente

Äquivalente können als `eq`, `Eq.`, `equiv`, `equiv.`, `Äquiv.` oder ausgeschrieben als `Äquivalente` bezeichnet werden.

**Für JSON beachten:** Alle diese Bezeichnungen müssen einheitlich als `equivalents` erfasst werden.

---

### Minuten

Minuten können als `min`, `Min.`, `mins` oder ausgeschrieben als `Minuten` bezeichnet werden.

**Für JSON beachten:** Alle diese Bezeichnungen müssen einheitlich als `min` erfasst werden.

---

### Stunden

Stunden können als `h`, `hr`, `hrs` oder ausgeschrieben als `Stunden` bezeichnet werden.

**Für JSON beachten:** Alle diese Bezeichnungen müssen einheitlich als `h` erfasst werden.

---

### konzentriert

Konzentriert kann als `konz.`, `konz` oder ausgeschrieben als `konzentriert` bezeichnet werden.

**Für JSON beachten:** Alle diese Bezeichnungen müssen einheitlich als `konzentriert` erfasst werden.

---

### gesättigt

Gesättigt kann als `sat.`, `sat` oder ausgeschrieben als `gesättigt` bezeichnet werden.

**Für JSON beachten:** Alle diese Bezeichnungen müssen einheitlich als `gesättigt` erfasst werden.

---

### über Nacht

Über Nacht kann als `ü.N.`, `üN`, `overnight` oder ausgeschrieben als `über Nacht` bezeichnet werden.

**Für JSON beachten:** Diese Bezeichnungen müssen einheitlich als `über Nacht` erfasst werden. Ist zusätzlich eine konkrete Dauer angegeben (z. B. `16 h` oder `18 h`), soll diese übernommen werden. Andernfalls darf keine Zeit angenommen oder ergänzt werden.

---

## Regeln für das strukturierte Vorschrift-Objekt

Das Feld `procedure` ist kein Freitext mehr, sondern ein strukturiertes Objekt mit drei Pflichtabschnitten: `Prep`, `Reaction` und `Workup`. Jeder Abschnitt enthält eine `Step`-Liste typisierter Schrittobjekte.

### Abgrenzung der Abschnitte

| Abschnitt | Inhalt |
|-----------|--------|
| `Prep` | Vorbereitung vor der Reaktion: Schutzgas einleiten, Lösungsmittel vorlegen, Edukt(e) lösen, Starttemperatur einstellen. |
| `Reaction` | Kernreaktion: Reagenzien zugeben, auf Reaktionstemperatur bringen, Reaktionszeit abwarten. |
| `Workup` | Aufarbeitung nach der Reaktion: quenchen, Extraktion, Waschen, Trocknen, Lösungsmittel entfernen, chromatografische Reinigung. Das Schlüsselwort „Aufarbeitung:" im Vorschrifttext markiert häufig den Beginn dieses Abschnitts. |

### Schritt-Typen und ihre Zuordnung

| `$xml_type` | Pflichtfelder | Optionale Felder | Einsatz |
|-------------|---------------|------------------|---------|
| `Add` | `_reagent`, `_amount` | `_dropwise`, `_repeat`, `_repeat_interval` | Zugabe eines Reagenzes oder Lösungsmittels; auch für Quench |
| `HeatChill` | `_temp` | `_time` | Temperaturänderung oder -haltung; `_time` nur wenn eine Dauer explizit im Text steht — niemals schätzen oder erfinden |
| `EvacuateAndRefill` | `_gas` | `_time` | Schutzgasatmosphäre herstellen, Entgasen |
| `Extract` | `_solvent` | `_repeat`, `_phase_kept` | Flüssig-flüssig-Extraktion (Lösungsmittel zugeben, Phasen trennen) |
| `WashPhase` | `_solution` | `_phase`, `_repeat` | Waschen einer Flüssigphase (org. oder wässr.) mit einer Lösung |
| `Wait` | `_time` | — | Warten oder Rühren ohne Temperaturänderung |
| `Dry` | — | `_desiccant`, `_time`, `_temp`, `_pressure` | Trocknen mit Trockenmittel (z. B. MgSO4); **nicht** für Lösungsmittelentfernung |
| `Evaporate` | — | `_method`, `_temp`, `_pressure` | Lösungsmittel entfernen am Roti oder unter Stickstoffstrom |
| `Purify` | `_eluent` | `_stationary_phase` | Säulenchromatographie; `_eluent` aus dem Fließtext; `eluent_system` beim Produkt **nur** aus der Produkttabellen-Zelle — nicht aus diesem Schritt ableiten |
| `Sonicate` | `_time` | — | Ultraschallbehandlung |

### Zuordnung typischer Formulierungen

| Formulierung im Text | `$xml_type` | Hinweis |
|----------------------|-------------|---------|
| „unter N2 lösen" / „Schutzgas" | `EvacuateAndRefill` | `_gas: "N2"`; als erster Prep-Schritt |
| „Entgasen (10 min)" | `EvacuateAndRefill` | `_gas: "N2"`, `_time: { "Value": 10, "Unit": "minute" }` |
| „zugeben" / „versetzen" / „lösen" | `Add` | `_reagent` = Name wie in `starting_materials`; `_amount` aus der Edukt-Tabelle |
| „X in Wasser geben" / „X in H2O lösen" | `Add` (H2O) + `Add` (X) + optional `Wait` | **Beide** Schritte anlegen: 1) Add H2O (aus `V mL` in starting_materials), 2) Add X (aus `g` in starting_materials), 3) Wait falls Zeitangabe vorhanden |
| „mit X und AcN versetzen" / „X in Acetonitril zugeben" | `Add` (AcN) + `Add` (X) | AcN wird **pro Bezugsstoff einmal** zugegeben: für Selectfluor erst AcN, dann Selectfluor; für Olefin nochmals AcN, dann Olefin — je ein eigener Add-Schritt |
| „tropfenweise zugeben" | `Add` | `_dropwise: true`; wichtig bei reaktiven Reagenzien (z. B. LAH) |
| „erneut mit selber Menge versetzen" / „(x2)" | `Add` | `_repeat: 2`, `_repeat_interval` falls Wartezeit angegeben (z. B. „nach 2 min") |
| „auf X °C erwärmen/kühlen und rühren für Y" | `HeatChill` | `_temp` und `_time` direkt aus dem Text |
| „rühren ü.N." / „über Nacht" | `HeatChill` | Bei expliziter Dauer diese direkt übernehmen; ohne explizite Dauer keine Zeit ergänzen, Hinweis ggf. in `_comment: "rühren über Nacht (ü.N.)"` erhalten |
| „rühren für X min" (ohne Temperaturänderung) | `Wait` | `_time` direkt; alternativ `HeatChill`, wenn Temperatur gehalten wird |
| „auf RT abkühlen" / „auf RT erwärmen" (ohne Zeitangabe) | `HeatChill` | `_temp: 25 °C`; `_time` weglassen (kein Standardwert!); `_comment: "Dauer nicht angegeben"` |
| „bei RT [versetzen / zugeben / rühren / ...]" | `HeatChill` (vor der jeweiligen Aktion) | `_temp: 25 °C`. Auch wenn der Text **keine** explizite Erwärmungs-/Kühlformulierung enthält, sondern nur als Bedingung „bei RT" nennt, muss ein `HeatChill`-Schritt auf 25 °C eingefügt werden — sonst geht die Temperaturbedingung verloren. Gilt analog für „bei 0 °C", „bei -20 °C" etc., falls ein vorheriger HeatChill-Schritt nicht bereits diese Temperatur einstellt. |
| „quenchen mit [Lösung]" | `Add` | `_reagent` = Quench-Reagenz; `_dropwise: true` **nur** wenn das Wort `tropfenweise`/`dropwise` wörtlich im Text steht (nicht aus Chemiewissen ableiten); Menge nur wenn im Text angegeben; wenn nicht angegeben, `_amount` weglassen und `_comment: "Menge nicht angegeben"` setzen |
| „mit DEE/DCM versetzen, Phasen trennen" | `Extract` | `_solvent` = Extraktionslösungsmittel; `_phase_kept: "organic"` |
| „mit DCM/MeOH 9:1 extrahieren" | `Extract` | `_solvent: "DCM/MeOH 9:1"`; Sonderbedingungen in `_comment` |
| „org. Phase mit Wasser waschen (2×)" | `WashPhase` | `_solution: "Wasser"`, `_phase: "organic"`, `_repeat: 2` |
| „mit brine waschen" / „mit NaCl-Lösung" | `WashPhase` | `_solution: "brine"`, `_phase: "organic"` |
| „mit HCl (1M) waschen" | `WashPhase` | `_solution: "HCl 1M"`, `_phase: "organic"` |
| „trocknen über MgSO4, abfiltrieren" | `Dry` | `_desiccant: "MgSO4"` |
| „LM am Roti entfernen" / „LM entfernen" | `Evaporate` | `_method: "rotary_evaporator"` |
| „einengen" | `Evaporate` | `_method: "rotary_evaporator"` oder `"vacuum"` |
| „Säule (Pe/EtOAc ...)" / „Säulenchromatographie" | `Purify` | `_eluent` = Laufmittelsystem inkl. Gradient aus dem Text; `eluent_system` beim Produkt nur aus der Produkttabellen-Zelle |

### Mengenangaben in Workup-Schritten

- Wenn die Menge explizit im Text angegeben ist (z. B. „gleiche Menge wie THF" → 50 mL), diesen Wert verwenden.
- Wenn sie nicht angegeben ist, **darf keine Menge geschätzt oder erfunden werden**. Das Feld `_amount` wird weggelassen, und in `_comment` wird vermerkt: `"Menge nicht angegeben"`.
- `Add`-Schritte werden auch ohne `_amount` aufgeführt, wenn die Zugabe im Text steht, aber keine Menge genannt wird — die Aktion ist trotzdem zu dokumentieren.
- `Extract`, `WashPhase`, `Dry`, `Evaporate` und `Purify` haben kein Pflicht-`_amount`.

### `_comment`-Nutzung

`_comment` ist optional, soll aber gesetzt werden, wenn der Schritt-Typ allein nicht alle Informationen des Originaltexts trägt. Der Kommentar muss aus dem Quelltext belegbar sein — es dürfen keine Sicherheitshinweise, Vorsichtsmaßregeln oder Begründungen aus chemischem Allgemeinwissen ergänzt werden:
- Sonderbedingungen: nur wenn wörtlich im Text, z. B. „OHNE zusätzliches Wasser", „sehr vorsichtig", „unter Eiskühlung"
- Fehlende Mengen: `"Menge nicht angegeben"` (kein Schätzen!)
- Zeitangaben für EvacuateAndRefill falls kein `_time` gesetzt wurde

### Abkürzungen und Standardwerte

| Abkürzung | Bedeutung | Wert im Schema |
|-----------|-----------|----------------|
| ü.N. | über Nacht | Keine implizite Dauer; explizite Zeitangabe nur übernehmen, wenn sie im Text steht |
| RT / Raumtemperatur | Raumtemperatur | `_temp: { "Value": 25, "Unit": "celsius" }` |
| Roti | Rotationsverdampfer | `Evaporate { _method: "rotary_evaporator" }` |
| 0 °C | Eisbad-Kühlung | `_temp: { "Value": 0, "Unit": "celsius" }` |
| (x2) / (2×) | Schritt zweimal | `_repeat: 2` bei Add; `_repeat: 2` bei WashPhase |
