# A divided road is one section

A divided road is a street whose two one-way carriageways run side by side with a median between them. The model makes it one
section and one space. Each carriageway keeps its own lanes and kerbs. The median is an island inside the space.

## The rule

1. **Two runs pair** when all of these conditions are true. Both runs are one-way. Both carry the same name. The runs lie side by
   side. No block lies between their lines. Side by side means that the middle of each line projects onto the inside of the other
   line, 2 m or more away from it. Two consecutive pieces of one road are not a pair. Each end of each line is within `DUAL_M` of the
   other line. `DUAL_M` is 30 m, a chosen value. The lines stay within `DUAL_M` over 80 % of their length.
2. **The pair is one section and one space.** The second run takes the section id and the space id of the first run. Each carriageway
   keeps its own lanes, strips, frame and kerbs on its own line. Nothing is moved.
3. **The median is the island of the space.** The walking side between the two roadways touches no block, so it is an island part
   of the one space. Where it is narrower than 8 m with nothing on it, it is paved roadway. Each sidewalk goes to the carriageway on
   its side.
4. **The width of the section** (`subsection.width_m`) is the two frames plus the median between them. The axis of the section is
   the line of the first run.

## What the rule does not do

- Two one-way streets with one name and buildings between them stay two sections.
- A divided road whose carriageways are more than 30 m apart stays two sections. The land between them is green of rank 1.
- A two-way road and a one-way service road beside it do not pair. The service road is not a street.

## Checks

U1 and U9 test that rank 3 and rank 5 have no overlap. B7 tests that no space reaches into a block. The division prints the pairs
it made.
