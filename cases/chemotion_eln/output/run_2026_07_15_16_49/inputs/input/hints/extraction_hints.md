# Extraction hints — Chemotion ELN records
Parse one cleaned Chemotion reaction record according to the target schema.

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
- `smiles`, `inchi`, and `inchikey` are native values already present on a resolved material entry. Copy each available value unchanged to the matching `starting_materials` or `products` entry; never derive identifiers or chemical properties from a name or from another identifier. Omit an unavailable identifier field.

## Parsing **plain_text_description** and **plain_text_observation**
- Ignore everything before the `Procedure` heading (narrative such as *Purposes*, *References*, *Analysis results*, *Obtained products*), the trailing `Analysis` section of the observation, and any text in **[square brackets]** (these are corrections/notes, not procedure).
- `Prep` and `Reaction` come from **plain_text_description**; `Workup` comes from **plain_text_observation**.
- Split by intent: preparing stock solution, preparing a setup, and adding starting materials → `Prep`; the reaction hold (e.g., "continue stirring for 2 h") → `Reaction`. Additional starting materials may be added in `Reaction` for two-stage reactions.
- When creating a `Step` element from these texts, emit the corresponding original line in `_comment`.
- When finding a line stating equipment, do not create a `Step` element but emit the corresponding original line at the beginning of `_comment` of the next `Step` with a semicolon separator. Also capture the vessel name ("50 mL flask", "5 mL vial", "Fritted funnel") and, if any, emit it in `_vessel` of the subsequent steps. Ignore non-vessel equipment such as pipettes and syringes.
- When finding a heading line such as "Reaction" or "Ag scavenging", emit it at the beginning of `_comment` of the next `Step` with a colon separator.
- When finding a line with an operation not defined in the schema (e.g., "Put into the glovebox") or ambient readings ("RT 21.6 °C RH 40%"), emit it at the beginning of the `_comment` of the next `Step` with a period separator.
- Following the above-mentioned rules, all the original texts between `Procedure` and `Analysis` should be captured in the `_comment` of the corresponding steps.
| Text | Step |
|---|---|
| "Add X" / "Add X µL/mL/mg" | `Add` (It must have a `_reagent`. If it is a chemical, `_reagent` must correspond to the `_name` of a `starting_materials` entry. Other types of addition, such as "reaction mixture", should also be considered as `_reagent`. Split into two entries if X is a solution of a solid in a solvent, and the written volume corresponds to the amount of the added solvent, while adding `dropwise` to both steps in case "dropwise" is mentioned.) If the reagent is not in the starting material list, write it in English form (not abbreviated). |
| "Sonicate for X" or other lines including "sonicate" | `Sonicate` (`_time`) as a subsequent step |
| "Continue stirring / stir for X" (reaction hold) | `Wait` (`_time`) |
| "at 0 °C" / another stated temperature | `HeatChill` (`_temp`) |
| "Heat to reflux" or similar description containing "reflux" | `HeatChill` (`_reflux: true`; include `_temp` only when a numeric temperature is also stated; never infer a reflux temperature from the solvent.) |
| "o/n" / "overnight" without a temperature condition | `Wait` (`_time`: 0.5 day) |
| "Remove volatiles with rotovap", "rotary evaporator" | `Evaporate` (`_method: "rotary_evaporator"`) |
| "Dry under vacuum / with suction" | `Dry` (`_time`) |
| "Filter → filtrate/residue", "Rinse with Y" | `Filter` (`_product_portion`, `_rinse: [{name, amount?}]`) |
- `Wait` is only for an explicit hold/stir of a stated duration and requires `_time`. An action with no duration — eluting a pad ("elute with THF") — is part of `Purify`, never `Wait`.
