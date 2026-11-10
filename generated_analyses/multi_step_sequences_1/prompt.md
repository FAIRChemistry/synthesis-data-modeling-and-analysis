Work in .

Use the JSON data in:
cases/excel_workbooks/output/run_2026_09_25_10_47/assembled/

The corresponding schema is:
cases/excel_workbooks/output/run_2026_09_25_10_47/inputs/schema_used.json

Reconstruct the synthesis routes from reagent journal references (e.g. ‘Aminoester 065’ → C065) and calculate overall yields as the product of step yields. Use C045 ‘sauber’, C063 ‘Säule 2 (sauber)’ (~29%) and C088 combined a+b.

Draw a compact left-to-right route diagram with experiment numbers, shared reaction-stage labels, colour-coded step yields and overall yields. Group similar branches from a common intermediate, showing their count and yield summary; keep unrelated precursors separate and omit isolated experiments. Mark missing yields and uncertain links, show partial yields for documented steps only, and flag carry-forward yields only with record evidence. Keep it readable at journal-page width with a short legend and caption explanations.

Create and run the analysis script. Save the script as generated_analyses/multi_step_sequences_1/multi_step_sequences.py, and save the diagram as PNG and PDF, dependency graph, chain yields and underlying numerical results in generated_analyses/multi_step_sequences_1/outputs/. Report the resulting file paths, a proposed caption and any ambiguities or missing data affecting the analysis. No Markdown results report is needed.
