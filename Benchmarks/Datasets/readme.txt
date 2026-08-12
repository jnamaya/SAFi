Benchmark input datasets — the --prompts files for the scripts in ../Scripts/.

    python Scripts/benchmark_runner.py          --profile fiduciary \
        --prompts Datasets/fiduciary_prompts.json --output Results/fiduciary_results.json
    python Scripts/baseline_benchmark_runner.py --profile fiduciary \
        --prompts Datasets/fiduciary_prompts.json --output Results/baseline_fiduciary_results.json

PROVENANCE. These two files were reconstructed on 2026-08-12 from the published
per-row results in ../Results/, which embed each case's prompt, id and
expected_will_decision. The original input files were not in the repository, so
the benchmark could not be re-run from a clean checkout even though all of its
evidence was published. Every field here is copied verbatim from the results —
nothing was re-authored — and both files were verified to reload identically
through each runner's own loading code.

One dataset per persona serves BOTH runners: the SAFi and baseline runs used
identical case sets (verified — same 100 ids, same prompts, same expected
decisions, per persona).

Shape is {"tests": [...]} rather than a bare list because
baseline_benchmark_runner.py reads data.get("tests", []); benchmark_runner.py
accepts either.

NOT YET RECORDED HERE: the Ideal / Out-of-Scope / Trap category label used by the
paper's per-category results table. It exists in no published artifact, which is
why those rows cannot currently be reproduced independently. A proposed labelling
is awaiting review; once confirmed it belongs in these files as a `category`
field.
