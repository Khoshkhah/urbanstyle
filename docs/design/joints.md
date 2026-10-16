# Joints: what can change along a street

**Superseded on 2026-10-16 by `sections.md`** (one frame per section, merges and forks as junctions, a connector inside the
intersection, the change classes). Kept for the history of the joint rules.

Status: agreed with Kaveh on 2026-10-16 ("we do not have a good protocol for a lane change, a fork or a merge"). A joint is where
two subsections of one section meet: the road between two junctions, where its cross-section changes. The rules say what can
change at a joint and what cannot. The code is in `network.py`, steps 6a to 6c.

## Rules

1. **Width is a section property.** The city's parking meters and the kerb evidence (catch basins) are judged once for the whole
   section, not per subsection. A kerb changes inside a section only where a source maps the change: an OSM `width`, an OSM
   parking tag that starts or ends, a lane count that changes. *Code: step 6a', 2026-10-16.*
2. **A split change moves only the centre line.** The same total, a different forward/backward count (a turn pocket): the kerbs
   stay, the line between the directions moves over 15 m. *Code: the continuity rule, step 6c.*
3. **A lane added or dropped changes the width by one lane on one side, over 15 m, never as a step.** At a merge, on the merging
   road's side. Elsewhere on the side of the lane that ends or begins: the outer lane of the direction whose count changes. *Code:
   the merge side in step 6c; the transition in step 8; the taper wedge in step 6b. Not yet: `turn:lanes` to name the side.*
4. **A fork is a merge read backwards.** The leaving road's lane continues out of the outer lane on its side, cut on the joint's
   bisector. *Code: the same `crosses()` and `align()` as a merge; a fork's lane continuity is not yet checked.*
   **A one-sided merge** (a road ends on a road that runs through the node, a Y; the ramp from West 6th into the Granville on-ramp
   at n2792935203): the merging road's lane should run on along the trunk's kerb on its side and narrow to nothing over 15 m. *Not in
   the code: a first version (2026-10-16) put the tail in the trunk's space and broke U2, U8, U9 and M1 at other merges; the merging
   road ends at the node today, with a gap to the trunk.*
5. **A merge or a fork is a joint, not a junction.** The road ends at a node are paired into streams; the node is a junction only
   where a road ends with no continuation or two streams cross. *Code: `crosses()`, `junctions.md` rule 1.*

## Checks

- R1 (INFO today): a step over 0.1 m in the roadway's edge at a joint. To become a FAIL where no source maps a change there.
- J4 (not yet): every joint with its cause: a width tag, a parking tag, a lane count, a merge, a fork, or none.

## What the rules leave open

- The side of an added lane where OSM maps no `turn:lanes` and no road merges: today the outer lane of the changed direction.
- A parking tag that ends mid-section with no meter and no kerb evidence: the kerb steps by 2.4 m there. OSM's tag is a source,
  so the step stands.
