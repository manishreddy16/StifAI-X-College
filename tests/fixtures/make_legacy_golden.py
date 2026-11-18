"""Regenerates tests/fixtures/legacy_golden.json from the CURRENT legacy retrieval path.

Only run this against the ORIGINAL (Phase 1B) retrieval code to refreeze behaviour:
the golden file is the specification that legacy mode must keep reproducing.
Usage: python tests/fixtures/make_legacy_golden.py [path/to/retrieval_module.py]
"""
import importlib.util, json, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.fixtures.heuristic_index import HEURISTIC_CHUNKS, HEURISTIC_QUERIES
from evaluation.synthetic.corpus import QUERIES, build_chunks_file


def write(path, rows):
    Path(path).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def load(module_path):
    spec = importlib.util.spec_from_file_location("api.retrieval_golden", module_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["api.retrieval_golden"] = mod
    spec.loader.exec_module(mod)
    return mod


def serve(mod, chunks_path):
    mod.FAST_CHUNKS_PATH = Path(chunks_path)
    mod.OLD_CHUNKS_PATH = Path(chunks_path).with_name("__none__.jsonl")
    mod._reset_state_for_tests()


def run(mod, queries):
    out = {}
    for q in queries:
        out[q] = [[h["chunk_id"], h["retrieval_score"]] for h in mod.retrieve(q, limit=10)]
    return out


def main():
    mod_path = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "api" / "retrieval.py")
    mod = load(mod_path)
    tmp = Path(tempfile.mkdtemp())
    heur = tmp / "heur.jsonl"
    write(heur, HEURISTIC_CHUNKS)
    syn = build_chunks_file(tmp / "syn")
    golden = {}
    serve(mod, heur)
    golden["heuristic"] = run(mod, HEURISTIC_QUERIES)
    serve(mod, syn)
    golden["synthetic"] = run(mod, [q.text for q in QUERIES])
    (ROOT / "tests" / "fixtures" / "legacy_golden.json").write_text(
        json.dumps(golden, ensure_ascii=False, indent=1), encoding="utf-8")
    print("golden written:", {k: len(v) for k, v in golden.items()})


main()
