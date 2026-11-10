# Extraction hints — Chemotion ELN records

Convert one cleaned Chemotion reaction record into the target schema.

## Anti-hallucination (binding)

- Use only what the record contains. Never invent or estimate amounts,
  temperatures, times, reagents, or steps. If a quantity is missing, omit the
  optional field (for an `Add` step, omit `_amount` and set
  `_comment: "amount not stated"`).
- `_dropwise: true` only if the text literally says "dropwise" (or "tropfenweise").
- Missing optional value → `null`. Do not fill gaps from chemical background
  knowledge.

## Metadata (map from the record)

- `journal_number` = `short_label`
- `reaction_name` = `name` (this field is **required**; always emit it, even when
  the name is long or parenthetical — never drop it).
- `date` = the date part (`YYYY-MM-DD`) of `created_at`
- `researcher`, `research_group`, `project_type` = the values in `case_metadata`
  (copy verbatim).
- `reagent_sources`: Chemotion exports carry no reagent storage locations, so emit
  an empty array `[]` (not `null`).

## Quantities come from the material entries, not the text

For `starting_materials` and `products`, take values from the record's resolved
entries, never from the free-text procedure:

- `name` = the entry's chemical `name` (this must match the `_reagent` used in
  the procedure); `note` = the entry's `short_label` (the in-house ELN id).
- `molar_mass_g_mol` = `molecular_weight`; `equivalents` = `equivalent`;
  `density_g_mL` = `density`. A resolved entry value of `0`/blank means "not
  recorded" → emit `null` for that field, never `0`.
- Convert `real_amount_value`/`real_amount_unit`: a mass unit (`g`, `mg`, `kg`)
  → `mass_g`; a volume unit (`l`, `ml`) → `volume_mL` (1 l = 1000 mL); then
  `amount_mmol = mass_g / molar_mass_g_mol * 1000` when both are known.
- `batch_volume_mL` = the main reaction solvent volume (e.g. the toluene volume);
  if unclear, use `vessel_size`.
- Product `yield_percent` may be stated in the "Analysis results" block of
  `plain_text_description` (e.g. "Yield: 71%"); other product values come from
  the resolved product entry.

## Procedure: which text feeds which section

- `Prep` and `Reaction` come from **plain_text_description**; `Workup` comes from
  **plain_text_observation**.
- Ignore everything before the `Procedure` / `Reaction` headings (narrative such
  as *Purposes*, *References*, *Analysis results*, *Obtained products*), the
  trailing `Analysis` section of the observation, and any text in **[square
  brackets]** (these are corrections/notes, not procedure).
- Split by intent: reagent/solvent additions and setup → `Prep`; the reaction
  hold (e.g. "continue stirring for 2 h") → `Reaction`; isolation and
  purification → `Workup`.
- Capture the vessel when named ("50 mL flask", "5 mL vial") in `_vessel`.
- Ignore non-procedural lines: "Cover with foil", "Start stirring at 400 rpm",
  ambient readings ("RT 21.6 °C RH 40%"), and pipette/syringe remarks.

## Step-type cues (Chemotion-specific)

| Text | Step |
|---|---|
| "Add X" / "Add X µL/mL/mg" | `Add` (amount from the material entry) |
| "Sonicate for X" | `Sonicate` (`_time`) |
| "Continue stirring / stir for X" (reaction hold) | `Wait` (`_time`) |
| "at 0 °C", "reflux", "o/n" | `HeatChill` (`_temp`; treat "o/n"/"overnight" as `_time` 0.5 day) |
| "Remove volatiles with rotovap", "rotary evaporator" | `Evaporate` (`_method: "rotary_evaporator"`) |
| "Dry under vacuum / with suction" | `Dry` (`_time`, no desiccant) |
| "Filter → filtrate/residue", "Rinse with Y" | `Filter` (`_product_portion`, `_rinse: [{name, amount?}]`) |
| "Extract with Y", "wash with Y" | `Extract` / `WashPhase` |

Keep the reagent names as written in the text (`Co(ttpp)`, `pyridine`, `AgOTf`,
`DCM`, `n-hexane`), matching `starting_materials.name` where the reagent is one.

### Step-shape rules (required fields)

- Every `Add` step must have a `_reagent`. For transferring or combining the
  crude itself ("add reaction mixture", "combine the mixture"), set
  `_reagent: "reaction mixture"` — do not emit an `Add` with only a `_comment`.
- `HeatChill` requires an explicit `_temp`. Cold storage with no stated
  temperature ("store in fridge/freezer overnight") is a `Wait` step with
  `_time` (o/n = 0.5 day) and `_comment: "store in fridge"`, not `HeatChill`.
- `Wait` is only for an explicit hold/stir of a stated duration and requires
  `_time`. An action with no duration — eluting or rinsing a pad/column ("elute
  with THF", "wash the plug with X and collect the eluate") — is a `Filter`
  (`_product_portion: "filtrate"`, `_rinse: [{name, amount?}]`), never `Wait`.
