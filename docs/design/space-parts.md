# The inside of a space: parts, marks and widths

<p class="lead">Every new space (an intersection or a subsection, <code>space.unit</code>) is divided into the parts you see on the street, with the lines painted on it and the width of every edge.</p>

Status (2026-10-08): agreed with Kaveh; built for intersections, roundabouts and subsections. Widths are measured from mapped sidewalks and crossings where they exist (see parts.py); the fixed sidewalk bands of the first version are gone. Built on the network-first spaces
([network first](network-first.md)).

## Parts (`space.part`)

The parts of a unit cover it exactly: no gaps, no overlaps (check U8). Each has a `type`, an `arm` (the road it belongs to, at an
intersection), a `direction` for a lane (`in` / `out` of the junction, or `forward` / `backward` along a subsection), a width where it has
one, and a `source`: `tag` (lanes / width tagged), `measured` (a mapped line: a crossing, a sidewalk, the measured kerb) or `default`.

| type | what | where it comes from |
|---|---|---|
| `junction box` | the shared turning area of an intersection, where the arms' carriageways meet | the carriageway minus every arm's own lanes |
| `lane` | one traffic lane, `in` or `out` (intersection), `forward` / `backward` (subsection) | lanes tag, else carriageway width / 3.25 m; two-way roads split either side of the centreline, right-hand traffic |
| `crosswalk` | a pedestrian crossing over the carriageway, 3 m wide | a mapped crossing path; else a crossing point, square across its road |
| `cycle crossing` / `cycle lane` | a cycle track over / along the carriageway, 2 m wide | mapped cycleways |
| `island` | a refuge in the carriageway | island tags (rare) |
| `sidewalk`, `furnishing`, `frontage` | the pedestrian realm: kerb side (1.8 m), building side (1.2 m), the rest | the space minus the carriageway, as `strips.py` bands it |
| `open` | ground beyond the reach of any measurement | the rest |

The **carriageway** is the measured travelway (`space.zone`, measured to the kerb where a sidewalk was found, else lanes × lane width).

At an **intersection**, each arm's lanes are the part of the carriageway that only that arm's road covers (its centreline ± half its
carriageway width); where two arms' carriageways meet, and the turning corners between them, is the junction box. Crosswalks are cut
out of lanes and box. The pedestrian realm falls apart into one **corner** per block corner.

## Marks (`space.mark`)

Lines painted or built on the street: `kerb` (where carriageway meets pedestrian realm), `stop line` / `give-way line` (across an arm's
`in` lanes at the junction side of its approach, where a stop or give-way sign or a traffic signal stands on that arm), `lane line`
(between two lanes of one direction), `centre line` (between the two directions).

## Edges and widths

Per intersection arm: total width at the cut, carriageway width at the cut, lanes in / out, sidewalk width on each side. Per subsection:
the same across its middle, and what bounds each side (building faces and their length, or open). Shown in the dashboard panel when the
space is selected; the map then shows exactly its parts, marks and objects.

## Limits

Widths are mostly estimated: in Monaco 45 % of roads carry a lanes tag, 3 % a width tag, 14 a turn-lanes tag. Islands are mapped 3 times.
No turn lanes, no parking, no bus lanes yet.
