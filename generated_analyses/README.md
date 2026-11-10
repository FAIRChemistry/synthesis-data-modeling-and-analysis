# Analysis runs

Each `<application>_<index>/` contains `prompt.md`, the generated application script and
`outputs/`. The index denotes the prompting attempt number. Most analyses have been generated within one attempt.
For `multi_step_sequences` a second prompt was sent to replace the boxes in the plot with molecule structures.

Run scripts from the repository root with converted records from the separately
published datasets or your own conversion runs. The dated paths in the prompts
record the original inputs; use the options below to point to your local data.
The analyses target the experiments described in the paper and require those
records for full reproduction.

| Analysis | Script | Options |
| --- | --- | --- |
| Parameter sweep | `parameter_sweep_1/parameter_sweep.py` | `--input <Excel assembled folder> --output <folder>` |
| Substrate scope | `substrate_scope_1/substrate_scope.py` | `--input <Excel assembled folder> --output <folder>` |
| Multistep sequences | `multi_step_sequences_1/multi_step_sequences.py` | `--input <Excel assembled folder> --output <folder>` |
| Multistep sequences with structures | `multi_step_sequences_2/multi_step_sequences.py` | `--input <Excel assembled folder> --workbooks <original xlsx folder> --output <folder>` |
| Product timeline | `product_timeline_1/product_timeline.py` | `--data <Chemotion assembled folder> --out <folder>` |
| Block-flow diagram | `block_flow_diagram_1/block_flow_diagram.py` | `--data <assembled folder> --record AD-R10 --output <folder>` |

Prefix each script path with `python generated_analyses/`. The molecular-structure
version requires Open Babel (`obabel`) and the original workbooks in addition to
the Python dependencies in `requirements.txt`.
