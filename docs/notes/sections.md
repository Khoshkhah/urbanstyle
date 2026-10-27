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
   there or two streams cross. The streams: each road end is paired with the end most opposite to it (within 45°). A junction
   node of the ground has a level-0 road at it: a node that only a bridge's ways (a profile's axes) and the ramps from it reach is
   the bridge's node, and its junction is the bridge's at level 1, not the ground's (Monaco, Avenue de France over Boulevard
   d'Italie: two ground intersections for the bridge's nodes lay over the real one; 2026-10-16). A landing keeps its junction, a
   level-0 road is there.
2. **Merges and forks are junction nodes.** A Y, a ramp joining a road, a slip lane leaving a road: roads meet there, whatever
   the angle. (Until 2026-10-16 a Y was a joint inside a section; the connector became a section of its own, with a walking wedge
   beside it: the bump at West 8th and the slip lane.)
3. **Connectors.** A road piece between two junction nodes that is shorter than `CONNECTOR_M` (40 m), or a `_link` piece under 40 m between
   them, belongs to one intersection together with both nodes. (2026-10-27: a longer `_link` is a section. As a connector its roadway was only a part
   of the intersection's shape, which the street's edge cut away: a 92 m link in the Portier tunnel lay in three pieces with bare gaps.) An intersection can hold several nodes and connectors (West 8th,
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
  the rest is a `paved` part ("paved roadway, no lane"; `carriageway` until 2026-10-16) whose `ref` names the frame, its widest way and the classes at the piece's
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
   `paved` part).
4. **The city's meters give parking only where the meters stand**, piece by piece; a strip that starts or stops is the class
   `parking`, inside the frame. (The old rule spread it along the section: a strip stood at the West 8th fork 40 m from its meter.)
5. **A piece of the walking part that touches no block and touches an island is that island's**, also an island of the next space.
   (The island's tip cut off into the Broadway junction was a raised furnishing triangle.)

## The rules from the Monaco fails (2026-10-16, night)

Monaco rebuilt with steps 2 and 3, its fails taken rule by rule. Each got one general rule, no place was patched:

1. **A junction node of the ground has a level-0 road at it** (rule 1 above). A node that only a bridge's ways and the ramps from it
   reach is the bridge's node. Avenue de France over Boulevard d'Italie: U1 3, J1 3, J2 1 to 0.
2. **A joint's cut is local to the joint**: a disc of the band's reach past it, not an infinite half-plane. A half-plane also cut the
   band wherever the line came back behind it, a hairpin or a long bend: Lacets Saint-Léon, Avenue des Spélugues and Avenue de La
   Quarantaine had lost 30-100 m of lanes. A3 12 to 1, U6 2 to 0.
3. **An arm is a run whose line ends at the node** (within 1 m), not one whose station there is near an end: a node beyond a line's
   end has station 0 at any distance. Boulevard Rainier III, 110 m off, was an arm of Rue Grimaldi's junction and three junctions
   along it became one cluster. U4 3, U5 3 to 0.
4. **A crossing piece counts where it runs across the road**: it meets the road's line at 30° or more, or, crossing no line (over a
   junction area), it is no longer than `XWALK_MAX_M` (40 m). A footway tagged crossing beside Boulevard du Larvotto for 80 m took
   the outer 1.5 m of its lane. A1 8 to 5; check X1 skips such a way too.
5. **A crossing is one object in one space**, in the parts too: the loser's crosswalk part goes where the winner's covers it
   (Boulevard de Suisse). U8 1 to 0.

The checks: R1 reads the shared boundary round the joint, its pieces across the road only (a folded section's two pieces run side
by side round an island: no joint), at level 0, and a bridge's deck is roadway; A1 reads the lanes' run that holds the line point
(a roundabout's far side 20 m on is not this place's). R1 4 to 0.

Left open on Monaco: A1 5 (four where a neighbour's lanes or cycle lane lie in our lane's space and the lane is cut at its edge: a
conflict to decide, split the overlap at the midline or narrow the lanes; one on a closed one-way loop, Avenue des Ligures, cause not
established), A3 1 (Avenue Marquet, the lane 1.65 m off its line), and the bridge model's BR3 4 (Avenue de France: deck edges with
no parapet among its connectors) and BR5 2 + 3 (Avenue de la Costa, Boulevard du Ténao: the model's own filling of the free deck
beside a 3 m lane leaves slivers).

## The room rule (2026-10-16, evening)

Kaveh: "when some elements partition something, the result must not have any overlap or any gap". The spaces of rank 3 were built
from the frame and never looked at the blocks: at West Broadway's 4-lane piece the section's 6-lane frame reached 2.5 m into the
block the sidewalk line had set (s0-w473754701.2/2 × b0-w23189661l.4, 84 m²). The rule:

1. **The street's edge of rank 1 caps every kerb.** For each run, the room on each side is the least distance from its line to the
   blocks and the paths' corridors (`space.block`, `space.corridor`), measured every 2.5 m out to 60 m (`network.room`). The frame's
   kerb on that side never passes it (`cap_room`), whatever the section's widest piece says.
2. **The lanes narrow before they are cut.** The sidewalk line is data, the lane width a chosen value: where the lanes and the strips
   do not fit between the two edges, the chosen lane width narrows on that piece, down to `LANE_MIN_M` 2.75 m, the count as OSM maps
   it (`width_method` `narrowed`, check B8). A width OSM maps is not narrowed. What still does not fit is cut at the edge.
3. **A joint where the cap changed the frame is the change class `room`** (`space.change`): a step there is a real change of the
   street's width as the sidewalk lines map it; R1 allows it, J4 names it.
4. **Every space is cut from the street of rank 1** at the end (`network.build`: the units, the parts and the marks less the blocks and
   the corridors), so a space reaching into a block is impossible by construction; check B7 tests the claim like G1 to G3 test the
   ground.
5. **The sidewalk strip is the kerb's limit too** (2026-10-16 evening, Kaveh: "why did it not use the footways for a better shape?").
   Every walkway at level 0 that is no crossing and has no corridor (a sidewalk line) is a strip, OSM's `width` or 2 m, centred on the
   line (`SW_HALF_M`): it is part of the street's edge for the room (the kerb ends at its near side; the block's edge is 1 m behind the
   line, its far side), and the junction's roadway is cut by it, so at a corner the kerb is the line's curve where OSM maps it and the
   4 m fillet only where it does not. The walking side there: the strip is the sidewalk part (position OSM, width chosen or OSM's),
   what lies between it and the roadway the furnishing zone (measured), what lies beyond it the frontage. Where no line is mapped the
   chosen bands stay (1 m furnishing, 1.8 m clear path from the kerb). A path's corridor ends at the street's edge (`blocks.py`): no
   mouth of street inside the slot.
6. **One partition of the walking side** (2026-10-16 evening, Kaveh: "why do the sections and intersections not have a clean shape?").
   The whole street of rank 1 is cut only by the cut lines, each arm's stop line and each joint between subsections, run across the
   street to the blocks' edges. The face between two cuts along a road is that section's, the face between a junction's arm cuts is
   that intersection's, corners included: the roadway with the most area inside a face owns the face, and every piece of the walking
   side goes to the owner of the face that holds it. A face with no roadway in it keeps the old rule, the roadway it touches most.
   Until then every piece went to the roadway it touched most, and a corner went to the section or the intersection by centimetres of
   shared edge: bites and hooks in every outline (Fir Street at West 8th), and the block corners were the sections' (i0-250765180).
7. **A divided road is one section** (`dual-carriageways.md`, 2026-10-16 evening): the two one-way carriageways of one street between
   the same two junctions are one section and one space, each with its own lanes and kerbs, the median between them the space's
   island. Two sections made the median go left and right piece by piece (Fir Street north of West Broadway).

## The roadway meets (2026-10-23)

With the dashboard's G button the ground and the sidewalks can be hidden, and the roadway alone showed gaps and steps at joints and
junction mouths. Two checks measure them: W1 (a street's line between two pieces of roadway with no roadway under it) and W2 (where
two spaces meet across a street, the roadway reaches the joint at different points on the two sides). Each place has its cause.
W2 at first also counted outline pieces along a kerb, the lines of roads that are no street (unnamed service roads), and dead ends;
it reads only the outline segments across a street now, and W1 skips a street's line that runs along a kerb (roadway on one side only: A1's). Monaco, the build of 2026-10-23 with the rules below: W1 1, W2 48.

The rules that came from them:

- **The room** (6a''): a walking way sets a road's room only where it lies beside the road, half a lane width or more from its line.
  A pedestrian way on Avenue Crovetto-Frères for 22 m gave the road's 375 m frame no room, and the road had no roadway at all.
  Monaco: A3 124 -> 1.
- **A short piece's heading**: an end's direction over 3 m of its line, or the whole piece where it is shorter. A 2.8 m piece of
  Avenue Albert II had no heading, and the T where Avenue des Papalins ends on it was no junction.
- **A bend between two sections**: two sections that end at one node with no junction are cut on the bisector there. Cut at
  7.42009, 43.73305: W2 13 -> 10. Open: a short piece (6.3 m) between such a bend and a junction is cut on a slant at the junction
  (n25193892).

- **A slit is roadway**: a piece of a space that no part covers (3 m² at most), with roadway of any space along half its outline or
  more and walking side along 5 % at most, becomes paved roadway (junction area in an intersection). The crosswalks are cut from
  the roadway, and the rest of a lane under 0.05 m² was dropped, or the cut and the crosswalk part were not the same shape. Monaco,
  full build: W2 48 -> 35 (13 places gone, none new), W1 1 -> 0, no other check changed; 387 slits filled. A space whose parts GEOS
  could not take from it (s0-w164338237/1) is skipped with a note in the build log.
- **W2's mark** is at the step itself (the middle of the longest piece where the two sides differ), not the middle of the joint: the
  mark lay up to 9 m from the step. With it, the 40 mouth places of the build before were 26 slits, 4 islands at the joint, 10
  walking side at the mouth. After the slit rule, of 27 mouth places: 13 sorted as slits, of which 7 are a block's corner near the
  mouth (walking side at the mouth) and 6 lie inside a space touching walking side or an island; 4 islands; 10 walking side.

Tried and not kept: W2 with islands counted as carriageway (a median's nose at a joint would be no step): W2 went 48 -> 119, because
an island at a joint beside a sidewalk counted as a step.

Tried and reverted: no fillet within a lane width of an arm's stop line (the mouth of a junction as wide as the arm). On a cut W2
went 9 -> 7; on Monaco it removed 24 shifts and made 27, because in a compact junction the corner between two arms lies in both
arms' mouths, and without its fillet it was a sharp notch. A crumb (a small piece of walking side between roadways) in a mouth kept
as walking side fixed one place but turned a crumb inside the roadway into furnishing. A mouth rule must keep the fillet where two
arms' mouths meet; it is open.

Open W2 causes (Monaco, 35): the junction's mouth wider or narrower than its arm, walking side there (about 17, with the 7 at a
block's corner); median noses at a joint (4; probably correct); a road that meets the side of a short arm instead of its stop line;
two sections, two subsections and two intersections (8).
