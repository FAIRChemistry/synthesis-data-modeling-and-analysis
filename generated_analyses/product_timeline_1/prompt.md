Work in .

Use the JSON data in:
cases/chemotion_eln/output/run_2026_07_17_19_26/assembled/

The corresponding schema is:
cases/chemotion_eln/output/run_2026_07_17_19_26/inputs/schema_used.json

Create a scatter plot with one circular point per synthesis entry: date on the X-axis, product substance on the Y-axis, circle area proportional to isolated product amount (mmol), and experiment code as the point label. Scale circles to keep sub-millimole amounts visible; show the two entries with missing amounts as empty circles. Group repeated substances on one row, reconciling names and formulas and ignoring bracketed run remarks (e.g. scale-up, discontinued). Draw arrows to later starting materials only when a product's short label reappears (e.g. AD-31 used as AD-31-1); matching substance names alone do not establish a link because starting materials may be purchased or older stock. Ensure readability at journal-page width, no overlapping labels, and a circle-size legend in mmol.

Create and run the analysis script. Save the script as generated_analyses/product_timeline_1/product_timeline.py, and save the plot and its underlying numerical results in generated_analyses/product_timeline_1/outputs/. Report the resulting file paths and any ambiguities or missing data affecting the analysis.
