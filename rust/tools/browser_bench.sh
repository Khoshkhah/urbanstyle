#!/bin/bash
# Makes the browser test of the whole chain in OUT (default data/cuts/browser-monaco): the page, the module and the input files under in/.
# duckOSM's pass-0 files are Zstandard, which the browser build cannot read: they are copied as Snappy here (pyarrow). Serve OUT over http.
set -e
cd "$(dirname "$0")/../.."
OUT=${1:-data/cuts/browser-monaco}
SIM=../simready/out/monaco-rust
P0=../simready/build/monaco/pass0-rust
mkdir -p "$OUT/in/fixtures" "$OUT/in/simready" "$OUT/in/pass0" "$OUT/in/features"
cp rust/www/index.html rust/www/worker.js "$OUT/"
cp rust/target/wasm32-unknown-unknown/release/urbanstyle_wasm.wasm "$OUT/urbanstyle.wasm"
for n in blocks division ground paths model element object check surface; do ln -sf "$PWD/data/cuts/monaco-$n-fixture.json" "$OUT/in/fixtures/"; done
for n in reference-line width-profiles lane-boundaries junction-cut junction-area connectors street-space; do ln -sf "$(realpath $SIM/$n.parquet)" "$OUT/in/simready/"; done
for n in data/cuts/features-monaco/*.parquet; do ln -sf "$PWD/$n" "$OUT/in/features/"; done
python3 - "$P0" "$OUT/in/pass0" <<'PY'
import sys, pyarrow.parquet as pq
for n in ["boundary_main", "edges_driving", "raw_ways", "raw_nodes"]:
    pq.write_table(pq.read_table(f"{sys.argv[1]}/{n}.parquet"), f"{sys.argv[2]}/{n}.parquet", compression="snappy")
PY
(cd "$OUT" && find in -name '*.json' -o -name '*.parquet' | sort | python3 -c 'import sys, json; print(json.dumps([l.strip() for l in sys.stdin]))' > files.json)
du -shL "$OUT/in" | tail -1
