# The comparison with SimReady: the log

Each entry is one comparison of urbanstyle's result with a SimReady build (`scope.md`, "How the two results are compared"). It
gives the method, the numbers and what the numbers do not show. SimReady records the decisions in its own rules.

## 2026-11-17: SimReady's junction areas against urbanstyle's blocks (Monaco)

SimReady build: `../simready/out/monaco-rust/build.duckdb` at SimReady commit f1d6f71. urbanstyle build: `data/monaco.duckdb`
(2026-10-24, the blocks of `blocks.py`). A junction area is roadway, so no part of it can be in a block.

```bash
../duckOSM/.venv/bin/python scripts/compare_junction_blocks.py ../simready/out/monaco-rust/build.duckdb data/monaco.duckdb 1
```

The full list is in `data/compare/monaco-junction-blocks-f1d6f71.txt` (not in git).

| | Junctions | Area in a block |
|---|---|---|
| all junctions at level 0 | 629 | 85,698 m2 of junction area |
| 90 % or more of the area in a block | 24 | 2,159 m2 |
| a part in a block, 20 m2 or more | 78 | 5,558 m2 |
| a part in a block, less than 20 m2 | 106 | 800 m2 |

- The 24 junctions that are whole in a block are at ways that urbanstyle has no street for (drives, parking aisles, unnamed
  service ways). 11 of them are in one block, `b0-w4224972r.162`. In urbanstyle these nodes are no junctions.
- A part in a block is a difference, not a fault of SimReady. The junction area can be too large (a corner radius, a mouth), or
  urbanstyle's street edge can be too near the road (the chosen 1.5 m where no building and no sidewalk sets the side). A place
  must be looked at before a rule changes.
- The two builds can have different OSM dates. This is not checked.

The places that SimReady named:

| Place | SimReady's area | In a block |
|---|---|---|
| n519323656 (Boulevard Louis II, a continuation) | 100.4 m2 | 10.0 m2 |
| n1684697734 with n1736930312 (a cluster) | 281.6 m2 | 162.2 m2 |
| n21912099 (Avenue de la Costa, a cluster of 5 nodes) | 551.7 m2 | 0.0 m2 |

SimReady's answer (2026-11-17, its commit 8874379):

- By the street arms of each junction (a drive is a service way with no name): no street arm 26 junctions 2,225 m2, one street
  arm 6 junctions 521 m2, two street arms 94 junctions 2,918 m2, three or more 81 junctions 2,853 m2.
- Decided by SimReady (rule row `GD.drive-network-in-block`, source `urbanstyle`, rejected): a junction of drives, car park
  aisles or unnamed service ways stays roadway, because vehicles drive there and the simulators need its lanes and turns. These
  junctions are a difference of class, not a fault. The script counts the junctions that are whole in a block apart.
- n519323656: SimReady's area is the lane surface only, so the 10 m2 in the block is urbanstyle's fault: the block edge is inside
  the lanes there. It is comparison code, so it is not corrected (`scope.md`).
- n1684697734: the 162 m2 supports SimReady's candidate `GD.drive-mouth-at-kerb`, its next change.
- The "15 junctions, 586 m2" is from urbanstyle's `simready-input.md` ("Faults for SimReady" 1), an older build. No list of
  nodes exists for it.
