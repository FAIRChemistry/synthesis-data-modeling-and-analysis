# Synthesis data modeling and analysis

Code accompanying *Digitalization of data analysis in organic synthesis by a schema-driven large language model workflow*.
The workflow converts Excel laboratory journals and
Chemotion ELN exports into validated JSON records using deterministic preprocessing,
JSON Schema, and an LLM. The structured records then enable many applications.
Implemented is a XDL export and reproducible LLM-generated analyses of reaction parameters, substrate scopes, synthesis routes, and product use.

## Installation

Use Python 3.12 or 3.13.

```bash
git clone https://github.com/FAIRChemistry/synthesis-data-modeling-and-analysis.git
cd synthesis-data-modeling-and-analysis
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

For chemical identifiers from embedded ChemDraw structures in Excel, also install
[Open Babel](https://openbabel.org/docs/Installation/install.html), with `obabel`
available on your PATH (e.g. `brew install open-babel` on macOS). It is also needed
to reproduce the synthesis-route plot with molecular structures.

## Usage

Run commands from the repository root. Place Excel workbooks in
`cases/excel_workbooks/input/workbooks/`, or replace
`cases/chemotion_eln/input/exports/export.json` with a Chemotion export. The bundled
Chemotion export can be used to try the workflow immediately.

For live conversion, create `config/secrets.json` with your API key:

```json
{"api_key_openai": "YOUR_OPENAI_API_KEY_HERE"}
```

Model and endpoint settings are in `config/config.json`.

```bash
python cli.py convert --case chemotion_eln
python cli.py convert --case excel_workbooks

# Inspect prompts or test the pipeline offline (no API key needed)
python cli.py convert --case chemotion_eln --dry-run
python cli.py convert --case chemotion_eln --mock

# Export a converted run to XDL, list runs, or compare two runs
python cli.py applications --case chemotion_eln RUN_ID
python cli.py list
python cli.py diff --case chemotion_eln RUN_A RUN_B
```

Results are saved under `cases/<case>/output/run_<timestamp>/`; `assembled/`
contains the converted JSON records. Mock mode produces placeholder records for
testing, rather than chemical extraction results.

The paper's analysis prompts and scripts are in
[`generated_analyses/`](generated_analyses/). They run independently of an
LLM on converted records; for example:

```bash
python generated_analyses/substrate_scope_1/substrate_scope.py \
  --input cases/excel_workbooks/output/RUN_ID/assembled \
  --output analysis_outputs/substrate_scope
```

## Tests

```bash
python -m pytest
```

The tests run offline without an API key.
