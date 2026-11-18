# Baselines

Save a baseline from a **real** run (real `rank-bm25`, real index, verified dataset):

    python -m evaluation --save-baseline before_change
    # ...change retrieval...
    python -m evaluation --compare evaluation/baselines/before_change.json

Every report records the sha256 of `api/retrieval.py`, the index sha256 and the dataset sha256, and the
comparison warns when index or dataset differ or when a run is not valid as real retrieval performance.

## Code baseline (no scores yet)
No baseline *scores* exist: this project contains no production index and no verified ground truth.
The retrieval code being protected as the "before" state is the Phase 1A final `api/retrieval.py`:

    sha256 66d3e8908bbc0d95a81a123085b801dfd0a6859a9dbba2b1cc435074e33f386c

Phase 1B did not change it.
