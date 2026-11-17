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

## 2026-11-17: SimReady asks for the rules behind four faults (Monaco, `data/monaco.duckdb` of 2026-10-24)

The numbers are from urbanstyle's network-first build, which is older than SimReady's build. They are not checked in the browser.

1. **Stop lines.** One line for each arm, cut square across the arm at its stop line: the far edge of the crosswalk that OSM maps
   within 15 m of the core, else 3 m past the core (`JUNC_ARM_M`, `junctions.md` rule 3). Never one for each lane, so a line does
   not step inside an arm. Monaco: 377 stop and give-way lines in 306 units, 1 pair of lines of two arms that cross. The ring of
   Sainte-Devote is one intersection (`i0-25193377`, 6 of the ring's 7 nodes) with 4 stop lines within 40 m of its centre.
2. **Junction clusters.** A junction is at a node of 3 or more road ends where a road ends or two streams cross. Two junction nodes
   are one intersection only if the road piece between them is under 40 m (`CONNECTOR_M`, chosen) or is a `_link`
   (`sections.md` rule 3). Monaco: 363 junction nodes in 214 intersections. Avenue du Port: `i0-25191904` and `i0-25192169` are two
   intersections, and node 1872542054 is no junction.
3. **Islands.** The strip between two frames of one section is an island where it is 2 m wide or more (`JGAP_M`); a thinner tail
   is paved roadway. The island keeps what is mapped on it. Monaco: 244 island parts (source `osm`, method `derived`). Near the
   Avenue du Port point (UTM 372939, 4843386) there are 3 island parts within 15 m. No refuge island is made from the leftover
   of a junction area: a paved strip inside an intersection is junction area (`street-rules.md` rule 15).
4. **Kerb.** The kerb is a result: the outer edge of the lanes and of the items that have a source (`street-rules.md` rule 3).
   Monaco: 1,743 kerb marks, 90.2 km, source `urbanstyle`, method `derived`. All 1,264 sidewalk parts are in a unit that has a
   kerb mark. This number is weak: the rule gives a kerb to every sidewalk. A city's catch basins only check the result (K1, no
   data in Monaco).
