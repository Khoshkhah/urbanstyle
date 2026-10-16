# Sections, intersections and the frame

Status: agreed with Kaveh on 2026-10-16. Replaces the joint rules of `joints.md` and the line-moving rules of `pipeline.md` step 6
(the continuity shift, the tapers of the kerb, the merge heading). The code follows this note; where the code differs, the note wins.

## The idea

A street is built once: its kerbs. Inside the kerbs the paint changes: lanes appear, turn pockets open, parking stops. So the
model has one **frame** per section, the driving part of the street between its two kerbs, and strips inside it. The walking
part is what lies between the frame and the block. The frame never moves sideways and never tapers unless a source says the kerb
moves.

## 1. Where the roads meet

1. **Junction nodes.** An OSM node where 3 or more road ends meet (a road that runs through counts 2), and where a road ends
   there or two streams cross. The streams: each road end is paired with the end most opposite to it (within 45°).
2. **Merges and forks are junction nodes.** A Y, a ramp joining a road, a slip lane leaving a road: roads meet there, whatever
   the angle. (Until 2026-10-16 a Y was a joint inside a section; the connector became a section of its own, with a walking wedge
   beside it: the bump at West 8th and the slip lane.)
3. **Connectors.** A road piece between two junction nodes that is shorter than `CONNECTOR_M` (40 m), or any `_link` piece between
   them, belongs to one intersection together with both nodes. An intersection can hold several nodes and connectors (West 8th,
   Fir Street and the ramp foot are one).
4. **The intersection's area.** The union of its arms' frames from each node to the arm's stop line (the far edge of OSM's crosswalk
   within 15 m, else 3 m past where the arms' frames overlap), with the connectors' frames, and corners rounded by 4 m.

## 2. Sections

5. A **section** is a road between two intersections, whatever OSM ways it is made of. It is named by its longest way,
   `s0-w<way>[.n]`.
6. The **frame** of a section is one width for the whole section: the lanes, both directions together, plus the parking, bike and
   bus strips a source gives, at the widest place of the section. Lanes are centred on the OSM line of the way they belong to. No
   line is moved sideways; no kerb tapers. Where OSM's lines of two ways are not aligned, the lanes jog inside the frame and the
   frame does not.
7. The **kerb** is the frame's edge on both sides, one line per section, cut where a crossing or a driveway crosses it.
8. A **subsection** is a piece of a section where the paint differs: a lane count, a turn pocket, a parking strip, an island. Its
   id is `<section>/<k>`. A subsection does not change the frame.

## 3. Is a change real?

Every place along a section where OSM's tags change is classified before it touches anything. Check J4 lists every place with
its class.

| Change in the data | Class | Frame | Inside the frame |
|---|---|---|---|
| The total is the same, the split differs (`lanes:forward` / `lanes:backward`) | turn pocket | no change | the centre line moves over 15 m |
| The total changes by the lanes of a road that merges or forks at a node | merge, fork | no change | the lane blends into the neighbour at the node |
| The total changes with `turn:lanes` naming a turn lane within 80 m of an intersection | turn pocket | no change | the median or the parking narrows for the pocket |
| A parking tag or the city's meters start or stop | parking | no change | the parking strip starts or stops; the lane beside it keeps its width |
| A median, an island way, a barrier way or a bridge's barrier starts | island, guardrail | no change | a strip inside the frame |
| The total changes, none of the above, and OSM `width` or the kerb evidence changes with it | real | the frame changes, with a kerb taper over 15 m (chosen) | |
| The total changes, none of the above, no width evidence | unknown | the frame keeps the wider count | the lane ends; paved roadway beside it; J4 reports the place |

The kerb evidence is the city's catch basins (a basin stands in the gutter at the kerb). It is read once per section side: the
median of the basins' offsets from the OSM line. It sets the frame only where no OSM `width` exists, and only where the roadway
is widened by parking (`pipeline.md` step 3) or narrowed below the chosen lane width down to 2.5 m a lane. It never moves a line.

## 4. The walking part

9. The walking part of a section is its block's side minus the frame: a furnishing strip at the kerb (1 m), the sidewalk (1.8 m),
   the frontage to the block. A corner between two arms belongs to the intersection.
10. A strip between two frames that touches no block is an island where a kerb, an object, a path or a barrier is mapped on it,
    else paved roadway with no lane. A strip that touches a block only at a corner (under 2 m) touches no block.
11. A service road that reaches a frame crosses the walking part to it as a driveway, as wide as OSM says, else 5 m.

## Checks

- J1: every intersection holds a junction node. J2: no intersection reaches outside its arms' frames. J3 (new): every connector lies
  in an intersection. J4 (new): every tag change along a section, with its class.
- R1: a step in a frame's edge is a FAIL unless J4 classes the place as real.
- A1: lanes centred on their OSM line, 0.5 m, no exceptions (the 2 m tolerance of the shift era goes).
- K1: the frame against the kerb evidence, INFO. K2: loose kerb ends.

## Order of work

1. This note, agreed. 2. The junction and connector rules (1 to 4) in `network.py`, on a 250 m cut at West 8th and at the
Granville ramp foot. **Done 2026-10-16** on two cuts (`scratch/cut.py`; the review `viz/review/sections-step2/`): every hard check passes;
the West 8th T on Fir Street's east carriageway stays its own intersection (OSM maps no road between the two carriageways there), and
chains of merge nodes make intersections 80-90 m long (the on-ramp foot, West 4th × West 6th, Granville × West 6th): to judge. 3. The frame per section (5 to 8), the change classes (section 3) and J3, J4; the shift, the tapers and the
merge heading removed. **Done 2026-10-16** on the same two cuts (`network.py` steps 6b and 6c; the review `viz/review/sections-step2/step3.html`):
every hard check passes with A1 at 0.5 m and R1 as a FAIL. 4. Both pilots rebuilt, the checks before and after, the page.

## How step 3 reads the table (the code's decisions, 2026-10-16)

- The classes are decided in this order: the same total with another split: `turn pocket`; a merging or forking arm: `merge` / `fork`;
  `turn:lanes`: `turn pocket`; an OSM `width` on both sides: `real`; else `unknown`. A parking or cycle strip that starts or stops
  with no lane change is `parking`; with a lane change, the note says it too. A joint where the lanes, the width and the strips are the
  same is `none` (OSM split the way for another tag).
- `merge` / `fork`: an arm of another section at a junction node within 80 m along the section, whose heading continues into the
  section (within 45°, as the streams of rule 1) and whose lanes (all, or one direction's) are the difference. A one-way arm that ends at
  the node is a merge, one that starts there a fork; a two-way arm is called a merge.
- `turn pocket` by `turn:lanes`: the wider way names a turn lane (`left`, `right`, `slight_*`, `sharp_*`, `reverse`) and the joint is within
  80 m along the section of a junction node. The pocket's kerb side (a one-way road: the side the turn names; two-way: `right` on that
  direction's kerb, `left` at the centre) gets no parking from the city's meters along the section; parking OSM maps on the way stays.
- `real`: both ways have OSM `width`, and the widths differ by over 0.5 m (or over 0.1 m a lane with the same count). The frame is
  computed per frame piece between `real` changes; the narrower piece gets a kerb taper over 15 m. No case in the two cuts yet.
- The island and guardrail class is not detected yet: no case in the cuts. The kerb evidence does not narrow a frame yet.
- The frame is the maximum on each side separately (the section's left kerb and right kerb are each one line). Where a piece is narrower,
  the rest is a `carriageway` part ("paved roadway, no lane") whose `ref` names the frame, its widest way and the classes at the piece's
  joints. A frame's rest never covers another road's own lanes (two parallel one-way ways of one street).
- The intersection's area takes the arms' frames (rule 4); the core (where the arms overlap) is read from the arms' own lanes, so two
  parallel arms with one wide frame do not overlap along their length.

## The rules from the Vancouver spots (2026-10-16, after step 3)

Kaveh checked the rebuilt unit spot by spot on his dashboard. Each spot got one general rule, in `network.py`:

1. **A merge or fork keeps the far kerb.** At a junction node where two arms side by side (the through arm q1 and a merging or
   forking arm q2: headings within 45°, the same flow, q2's band on q1's band over more than both roadways' widths) continue into one
   section whose lanes are q1's plus q2's, that section keeps q1's kerb on the side away from q2. Its lanes sit half of q2's width off
   the OSM line toward q2 (`space.subsection.left_extra`; check A1 expects it), its frame with them, and inside the intersection q2's
   band lies beside q1's. This is the one place where lanes leave the OSM line: OSM draws the ramp's line and the 3-lane line as one
   straight line at West 8th, so centred lanes stuck out 1.6 m on both sides there (the bump). The two one-way carriageways of one
   street joining into its two-way way flow opposite ways: no merge, no move.
2. **An island begins where the strip between two frames is 2 m wide** (`JGAP_M`). A thinner tail with no kerb, object, path or
   barrier on it is paved roadway, cut off square. The island's wide part keeps what is mapped on it. (A wedge ran 20 m into the
   junction at West 4th × West 6th.)
3. **Inside an intersection a paved strip between roadways is junction area**, one surface with it (a section's strip stays a
   `carriageway` part).
4. **The city's meters give parking only where the meters stand**, piece by piece; a strip that starts or stops is the class
   `parking`, inside the frame. (The old rule spread it along the section: a strip stood at the West 8th fork 40 m from its meter.)
5. **A piece of the walking part that touches no block and touches an island is that island's**, also an island of the next space.
   (The island's tip cut off into the Broadway junction was a raised furnishing triangle.)
