# The street space

This page explains how urbanstyle divides a city's streets, and why. The rules behind each step are in the
[design](../design/index.md).

## The street starts from the blocks

A street is the ground between the blocks. urbanstyle first finds the blocks: the land that the streets enclose, with its buildings,
yards and car parks. What is outside the blocks is the street space.

Most tools start from the road's center line and draw the street as a band of fixed width around it. That band is wrong wherever a
street widens, narrows, or has a plaza beside it. Starting from the blocks gives the street its real outline, from building line to
building line. A city's parcels set that line where the city publishes them.

## Sections and intersections

The street space is divided along the street:

- An **intersection** is where streets meet. It is a space of its own, and it belongs to all the streets that meet there.
- A **section** is the stretch of one street between two intersections, between the same two blocks.
- A **subsection** is a piece of a section where the cross-section stays the same: a section is divided where lanes are added or
  dropped.

This is the division that CityGML 3.0 (`Section`, `Intersection`) and IFC 4.3 (`ROADSEGMENT`, `INTERSECTION`) use. A city can thus
read the result in the standards that it knows.

## Parts across the street

Each subsection and intersection is divided across, into parts:

- the roadway: lanes (forward and backward), shoulders, parking, bus zones, and one junction area in each intersection;
- the medians and the islands;
- the pedestrian realm, in NACTO's zones: the kerb, the furnishing zone, the walking zone and the frontage;
- the crossings, and the pedestrian corners of the intersections.

The parts lie as strips parallel to the subsection's axis. A position in a street is therefore also a pair (s, t): s metres along
the axis, and t metres across it, positive to the left.

The painted lines (lane lines, center lines, stop lines, zebras, arrows) are in their own table. The lane-to-lane moves through an
intersection come from SUMO, run on urbanstyle's own lanes.

## Levels

Streets are not all on the ground. Each space has a level, from −2 to 2: 0 is the ground, 1 is a bridge deck above it, −1 a tunnel
under it. The ramps, stairs and lifts that join two levels are links of their own. The dashboard shows each level full, faded or
hidden, so a street under a bridge can be seen through it.

Bridges get more than a level. A bridge has a profile with its axes and its heights along them, measured from LiDAR where the city
publishes it, so the deck stands at its real height.

## Objects

Lamps, trees, signs, benches, hydrants, parking meters and manholes stand in the street. Each source describes them in its own way:
OpenStreetMap maps some, the city's survey lists others, and street-level photos show many of both. urbanstyle matches them, so
that each real object is one object, with every source's id and what each source says of it. Mapillary's photos only confirm
objects. Their positions are too rough to make one.

## Why areas, and not only lines

Network models (OpenStreetMap, Overture, GMNS) describe a street as a line with tags. A line is enough to route a car, but it cannot
answer a planner's questions: how wide is the sidewalk here, how much of this street is for people, what stands in the way.
urbanstyle keeps the areas, and builds the lines from them when a tool needs a network. The walking network for OpenSidewalks is
one example.

## Related

- How a value's source is recorded: [Sources and accuracy](sources.md).
- How this model compares with the standards: [The format and the standards](standards.md).
- Every table and field: [Tables](../reference/tables.md).
