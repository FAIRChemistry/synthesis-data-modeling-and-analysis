# excel_workbooks: conversion output history

Each row describes saved-input changes from the preceding run in chronological order. All runs used gpt-5-mini and completed with zero conversion failures. Small hint revisions and source-data corrections are identified in the table.

`results/` contains generated records (some legacy runs also copied earlier records into it); `assembled/` contains the combined record set. Regenerated counts and validation results come from `summary.json` and `run_complete.json`. A partial run does not regenerate every record whose source snapshot changed.

| Run | Type, scope and validation | Hint changes | Source-data changes | Other saved inputs |
| --- | --- | --- | --- | --- |
| [run_2026_06_15_11_55](run_2026_06_15_11_55/) | Baseline. 47 regenerated; 47 assembled; 47 valid / 0 warnings. | Baseline extraction hints and general LLM hints. | Baseline set of 47 workbooks. | Baseline saved inputs. |
| [run_2026_08_13_12_20](run_2026_08_13_12_20/) | Hints, examples and source-text corrections. 1 regenerated; 47 assembled; 1 valid / 0 warnings. | Add rules to copy native structure identifiers without inference; distinguish degassed solvent additions from vessel evacuation and retain solvent pretreatment comments. | C113 A28: explicitly add two water and two brine washes. C125 A28: clarify that the first acetonitrile portion was previously degassed. Only C125 was regenerated; the C113 source edit does not imply a regenerated C113 result. | Schema files updated; 4 example file changes ([input comparison](run_2026_08_13_12_20/diffs/rundiff_inputs.html)). |
| [run_2026_08_13_12_30](run_2026_08_13_12_30/) | Targeted hint and schema change. 1 regenerated; 47 assembled; 1 valid / 0 warnings. | Represent degassed additions with _degassed: true instead of free-text comments; clarify that the flag belongs to the solvent in split solution additions. Activate extraction_hints_current.md. | Raw workbooks unchanged; regenerate C125 only. | Schema files updated ([input comparison](run_2026_08_13_12_30/diffs/rundiff_inputs.html)). |
| [run_2026_09_08_18_23](run_2026_09_08_18_23/) | Small hint change and corrected source data. 5 regenerated; 47 assembled; 5 valid / 0 warnings. | Give the prepared table precedence over conflicting procedure text, including explicit repetition counts (xN). This is a small edit with a substantive interpretation change. | C115: correct K8 total-volume formula and K10:K13 number-format strings. C118/C122/C123 A15: change the water association from iron nitrate to iron oxalate. C102/C104 added to the input snapshot but not converted. Regenerate C115, C118, C121, C122 and C123. | No schema/example changes. |
| [run_2026_09_25_10_47](run_2026_09_25_10_47/) | Source-data corrections; hints unchanged. 2 regenerated; 47 assembled; 2 valid / 0 warnings. | No saved hint, schema or example changes; this is a data-correction run, not another hint-development iteration. | C063: correct L-Phe to L-Ile precursor, DCM reagent label and product-purity labels (A10/A14/A23/A24). C116: correct iron nitrate to hydrated iron oxalate, the associated water label and location (A11/A15/J38). Regenerate C063 and C116. | No schema/example changes. |

## Source corrections and coverage

The September 25 run corrects source data with unchanged hints. C102 and C104 occur in later raw snapshots but are not part of the 47 converted records. The final `assembled/` directory combines records generated at different times.

## Metadata and comparisons

[runs.json](runs.json) indexes the run folders. `previous_run` identifies the baseline used for comparison, which can differ from the preceding chronological row. Each comparison is available in the corresponding run's `diffs/` directory. Paths in metadata and saved input snapshots are relative to the repository/archive root.
