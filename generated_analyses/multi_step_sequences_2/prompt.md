Work in .

Use the existing script generated_analyses/multi_step_sequences_1/multi_step_sequences.py and its outputs in generated_analyses/multi_step_sequences_1/outputs/ as the starting point.

Use the JSON data in:
cases/excel_workbooks/output/run_2026_09_25_10_47/assembled/

The corresponding schema is:
cases/excel_workbooks/output/run_2026_09_25_10_47/inputs/schema_used.json

Structure identifiers are in products[].smiles/inchi and starting_materials[].smiles/inchi, but coverage is incomplete. The same run's inputs/input/workbooks/ contains native ChemDraw drawings for all 39 connected experiments; src/preprocess.py::extract_embedded_chemical_structures extracts them using olefile and Open Babel (obabel). Complete products extract for 27 experiments; the other 12 require resolving labels such as NH3Cl or O2N from the native drawings. Report unresolved structures rather than guessing, and distinguish selected products from side products, particularly in C083/C091.

Replace the experiment-code boxes with RDKit drawings of the selected products only, without boxes or outlines, placing small experiment IDs above and yields below. Preserve the existing analysis, grouping, yield colouring and uncertainty indicators, and keep the figure readable at paper width.

Create and run the updated script as generated_analyses/multi_step_sequences_2/multi_step_sequences.py, saving PNG/PDF plots and underlying numerical results in generated_analyses/multi_step_sequences_2/outputs/. Check numerical agreement with attempt 1 and report output paths, structure ambiguities and a proposed caption. Leave earlier attempts and the paper unchanged; no Markdown results report is needed.
