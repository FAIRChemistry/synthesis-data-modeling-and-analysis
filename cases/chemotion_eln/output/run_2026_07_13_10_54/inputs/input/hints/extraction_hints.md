# Extraction hints — Chemotion ELN records
Convert one cleaned Chemotion reaction record into the target schema.

## Anti-hallucination (binding)
- Use only what the record contains. Never invent or estimate amounts, temperatures, times, reagents, or steps. If a quantity is missing, omit the optional field (for an `Add` step, omit `_amount`).
- `_dropwise: true` only if the text literally says "dropwise".
- Missing optional value → `null`. Do not fill gaps from chemical background knowledge.

## Metadata (map from the record)
- `journal_number` = `short_label`
- `reaction_name` = `name` (this field is **required**; always emit it, even when the name is long or parenthetical — never drop it).
- `date` = the date part (`YYYY-MM-DD`) of `created_at`

## Quantities come from the material entries, not the text
For `starting_materials` and `products`, take values from the record's resolved entries, never from **plain_text_description**:
- `name` = the entry's chemical `name` (this must match the `_reagent` used in the procedure).
- `note` = the entry's `short_label`.
- `molar_mass_g_mol` = `molecular_weight`; `equivalents` = `equivalent`; `density_g_mL` = `density`. A resolved entry value of `0`/blank means "not recorded" → emit `null` for that field, never `0`.
- Convert `real_amount_value`/`real_amount_unit`: a mass unit (`g`, `mg`, `kg`) → `mass_g`; a volume unit (`l`, `ml`) → `volume_mL` (1 l = 1000 mL); then `amount_mmol = mass_g / molar_mass_g_mol * 1000` when both are known.
- Rounding to an appropriate number of decimal places is acceptable (e.g. 1.21218 g → 1.21 g); never round so far that information is lost.
- `batch_volume_mL` = sum of `volume_mL` of all `starting_materials` .
-  Product `yield_percent` = `equivalent` * 100.

## Procedure: which text feeds which section
- `Prep` and `Reaction` come from **plain_text_description**; `Workup` comes from **plain_text_observation**.
- When creating `Step` element from these texts, emit the corresponding original line in `_comment`.
- Ignore everything before the `Procedure` / `Reaction` headings (narrative such as *Purposes*, *References*, *Analysis results*, *Obtained products*), the trailing `Analysis` section of the observation, and any text in **[square brackets]** (these are corrections/notes, not procedure).
- Split by intent: starting material additions and setup → `Prep`; the reaction hold (e.g. "continue stirring for 2 h") → `Reaction`; isolation and purification → `Workup`.
- Capture the vessel when named ("50 mL flask", "5 mL vial") in `_vessel`.
- Ignore the types of steps that are not implemented in the schema: e.g. "Cover with foil", "Start stirring at 400 rpm"
- Ignore ambient readings ("RT 21.6 °C RH 40%")
- Ignore non-vessel equipment statements such as pipettes and syringes.

## Step-type cues (Chemotion-specific)
| Text | Step |
|---|---|
| "Add X" / "Add X µL/mL/mg" | `Add` (amount from the material entry, split into two entries if X is a solution of a solid in a solvent. The written volume corresponds to the amount of the added solvent) |
| "Sonicate for X" | `Sonicate` (`_time`) |
| "Continue stirring / stir for X" (reaction hold) | `Wait` (`_time`) |
| "at 0 °C" / another stated temperature | `HeatChill` (`_temp`) |
| "reflux" | `HeatChill` (`_reflux: true`; include `_temp` only when a numeric temperature is also stated) |
| "o/n" / "overnight" without a temperature condition | `Wait` (`_time`: 0.5 day) |
| "Remove volatiles with rotovap", "rotary evaporator" | `Evaporate` (`_method: "rotary_evaporator"`) |
| "Dry under vacuum / with suction" | `Dry` (`_time`) |
| "Filter → filtrate/residue", "Rinse with Y" | `Filter` (`_product_portion`, `_rinse: [{name, amount?}]`) |
Keep the reagent names as written in the text (`Co(ttpp)`, `pyridine`, `AgOTf`, `DCM`, `n-hexane`), matching `starting_materials.name` where the reagent is one.

### Step-shape rules (required fields)
- Every `Add` step must have a `_reagent`. For transferring or combining the crude itself ("add reaction mixture", "combine the mixture"), set `_reagent: "reaction mixture"` — do not emit an `Add` with only a `_comment`.
- Every `HeatChill` requires either an explicit `_temp` or `_reflux: true`; never infer a reflux temperature from the solvent.
- `Wait` is only for an explicit hold/stir of a stated duration and requires `_time`. An action with no duration — eluting a pad ("elute with THF") — is part of `Purify`, never `Wait`.
