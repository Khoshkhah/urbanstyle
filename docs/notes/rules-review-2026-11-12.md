# Review of the street rules (2026-11-12)

Kaveh, 2026-11-12: "I think you need to review all rules again. I think we are patching rules again and again without any logic."
This note lists the rules that make the current build, puts each fault of 2026-11-12 on its rule, and proposes one model for the
part of the street that has no source. Section 7 gives what was built and decided.

## 1. What makes the current build

The Monaco dashboard (`data/monaco-sr3.duckdb`) is a build with `--simready`: SimReady makes the roadway, urbanstyle makes the rest
(`simready.py`, `sr_blocks.py`). The table gives each rule, what it reads and what kind of value it gives.

| Step | Rule | Reads | Kind of value |
|---|---|---|---|
| Street at level 0 (rank 1) | the area less the blocks and the corridors | SimReady's street face (made by urbanstyle's block method), OSM's pedestrian ways | source, with chosen distances where no sidewalk or building sets a side (`MIN_EDGE_M` 1.5 m, `SIDEWALK_ZONE_M` 8 m) |
| Street off level 0 | SimReady's street faces of that level | SimReady | source |
| Sections, intersections, lanes, junction areas, stop lines, moves | as SimReady gives them | SimReady | source |
| Islands of the roadway | SimReady's islands (`island-extraction`) | SimReady | source |
| Walking side | the street less SimReady's roadway | the two above | **residue**: what is left |
| Cuts of the walking side | each section's two ends, run `CUT_M` each way | SimReady's lanes | derived |
| Owner of a piece | the space whose roadway it touches most | geometry | derived |
| Island of the walking side | a piece that runs less than `EDGE_TOUCH_M` (1 m) along the street's edge | geometry | **threshold** |
| Bands of a side | furnishing `FURNISH_M` 1.0 m from the kerb, sidewalk `CLEAR_M` 1.8 m, the rest frontage | nothing | **chosen** |
| Off level 0 (since 697f502) | OSM's footways and cycleways of that level only | OSM | source |
| Kerb mark | the roadway's edge where it faces a piece of the walking side | geometry | derived, drawn as a raised stone in 3D |
| Crosswalks, driveways | OSM's crossings; unnamed service ways | OSM | source, chosen widths |
| Deck heights | the bridge profile's heights above a flat ground at 0 m | profile | derived from chosen grades |
| Street objects in 3D | an OSM object at level 0 stands on the ground, also under a deck | OSM | source, level rule |

Two rules give values with no source: the bands (chosen widths) and the island threshold. Both act on the residue.

## 2. The faults of 2026-11-12 and their rules

| Fault (Kaveh's picture) | Place | Rule that makes it | Class |
|---|---|---|---|
| A frontage on every bridge | `s2-w209518052/1#5` and 19 more decks, 97 in tunnels | bands on the residue: the deck's face is wider than its lanes | residue |
| Furnishing, sidewalk and kerb in the middle of a junction | `i0-1736937871#5` | the residue wedge touches the block at a 2 m tip, so it is a side, not an island, and gets bands and a kerb | residue |
| A raised slab across the road at a bridge end | Saint-Roman, `i2-21927897` | the flat ground: the upper town's level-2 roads must reach 0 m at the hairpin | height |
| A junction area bent up by 5 m | Saint-Roman, `i1-1080509835#1` | the flat ground: level 2 lies under level 1 | height |
| A bus stop through the deck | Chapelle Saint-Roman | the object level rule, with the deck 1.2 m high there (flat ground) | height |
| A building missing over the road | Fairmont, `r2093796` | OSM (and Overture) map a hole over Boulevard du Larvotto and Louis II | source gap |
| No lane lines on a bridge | Avenue de France | not reviewed yet | open |

## 3. Why the fixes did not converge

The roadway has a source (SimReady), and the street's outer edge has a source (the street face). The walking side has none: it is
what is left between them. The build then gives the residue a shape it does not know (three bands, a kerb) and decides by a threshold
whether it is a side or an island. Every place where the roadway and the street face disagree makes a new residue shape: a wedge at a
junction, a strip on a deck, a slit in a tunnel. A fix for one shape (no bands on decks, an island share) is one more threshold, and
the next shape breaks it.

The height faults have a different cause: the model draws everything on a flat ground at 0 m, and Saint-Roman is a hillside. No rule
about the parts can fix them.

## 4. Proposal: the walking side from sources only

One rule, at every level and in every space, with no threshold:

1. **A part of the walking side has a source**, as a lane does:
   - `sidewalk`: a whole piece of the walking side (from the roadway to the street's edge) where an OSM footway or cycleway runs in
     it for 2 m or more, or where the nearest road's sidewalk tag covers its side. No width is chosen;
   - `island`: SimReady's island, or a piece that OSM maps as a traffic island;
   - `crosswalk`, `driveway`, `bus stop`: as now.
2. **The rest is one part, `unmapped`** (one word, new; `verge` already means OSM's grass in `ground.py`): the residue between the roadway and the street's edge that no source describes.
   It has no bands, no chosen widths, and the page draws it flat at the roadway's height.
3. **The kerb is drawn only where a sourced part meets the roadway** (a sidewalk, an island) or where OSM maps a kerb (`barrier=kerb`,
   `kerb=*`). An unmapped piece meets the roadway with no kerb.
4. The furnishing and the frontage bands are removed. Their words stay for a city's data that maps them.

What this changes in the faults of section 2: the deck frontages and the junction wedge become a flat unmapped part with no kerb; the deck
keeps the OSM footways it has. The height faults stay: they need a decision of their own (section 5).

What it costs: a street with no OSM sidewalk line and no sidewalk tag shows a flat unmapped part, not a sidewalk. That is what the sources say. The check G1
(no unknown ground) stays true: an unmapped part is street.

The design chapters (`parts.md`, `spaces.md`, the glossary) change with it, and the check U9 and the dashboard's colours follow.

## 5. The heights: a separate decision

The flat ground makes the Saint-Roman faults and the bus stop through the deck. The options, from the 2026-10-17 note
(`monaco-saint-roman-terrain`) and the ground standard of 2026-11-09:

1. **Keep the deck in the air at the hairpin**: a2 does not come down to 0 m; the ground road `w4246253` is a ramp up to it.
2. **Draw the street on the area's ground**: every part at the base height of today's bridge work (duckOSM's DTM, FABDEM 30 m). FABDEM
   gives 53 to 55 m round Saint-Roman, too smooth for a 5 to 10 m hillside, so this does not fix Saint-Roman by itself.

## 6. Next steps (after agreement)

1. Agree section 4 (the walking side) or change it.
2. Try it on two cuts: Saint-Roman and the junction `i0-1736937871`; pictures before and after at both.
3. Count the parts that change on the whole of Monaco: sidewalks, unmapped parts, islands, kerb length.
4. Decide section 5 apart from it.

## 7. Built and decided (2026-11-12)

Tried on two cuts with SimReady's input (Saint-Roman 7.4384, 43.7518 and the Larvotto junction 7.42986, 43.74166, 150 m), in a
box of 220 m round each place, against `data/monaco-sr3.duckdb`:

| | Saint-Roman before | after | Larvotto before | after |
|---|---|---|---|---|
| kerb | 1,656 m | 717 m | 1,541 m | 1,246 m |
| sidewalk | 1,471 m2 | 2,281 m2 | 1,518 m2 | 4,356 m2 |
| unmapped | 0 | 1,848 m2 | 0 | 996 m2 |
| furnishing and frontage | 2,516 m2 | 0 | 2,924 m2 | 0 |

U8, U9, G1-G3, L1, L2 and B7 pass on both cuts. The junction `i0-1736937871` has no band and no kerb now. Its biggest unmapped piece
(25 m2) is the ground under the Boulevard du Larvotto bridge (way 92627405).

SimReady and urbanstyle compared the places where both give an answer (Kaveh: "you two must talk more to each other and compare").
Agreed, and accepted by Kaveh ("go ahead"):

1. The street's edge at level 0: urbanstyle (blocks and corridors). SimReady's ground face only bounds its kerbs.
2. A roundabout's central island: SimReady's island is the source. 28 of Monaco's 32 central islands (2,622 m2) were in no block
   and urbanstyle made them walking side; urbanstyle now takes them as islands where they lie in the street.
3. The edges of the faces off level 0: SimReady. Its commit b125c76 took the face area with no roadway from 7,726 to 5,788 m2;
   it adds a later step that cuts each face to its final lanes (after the kerb profile, D37).
4. Lane ends that miss their junction area: SimReady (commit a781284: 35 to 27).
5. The ground under a bridge: no source; it stays unmapped.
6. The walking side: urbanstyle's rule above. SimReady has no sidewalk shapes.

The build without SimReady (`network.py`) keeps its bands; this rule is the SimReady build's.
