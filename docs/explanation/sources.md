# Sources and accuracy

This page explains why every value in urbanstyle names where it comes from, and how its accuracy will be added and improved.

## Why every value names its source

A street-space model mixes many sources. The lanes come from OpenStreetMap, the sidewalk width from the building line, a lamp's
position from the city's survey, a bridge's height from LiDAR. If a value is wrong, a planner must know which source to fix. If two
sources disagree, the user must see both.

So each value carries its source and its method:

| Method | Meaning | Example |
|---|---|---|
| mapped | a source drew or tagged it | a lane count from OpenStreetMap |
| measured | an instrument measured it | a deck height from LiDAR |
| observed | a photo showed it | a sign that Mapillary detected |
| derived | urbanstyle computed it from other values | a sidewalk width between the kerb and the building line |
| chosen | no source gives it, and urbanstyle chose it | a lane width of 3.25 m where nothing measures it |

There is no "default" value. A value that no source gives is urbanstyle's own, and its method says so. A city can then replace each
chosen value with a measured one, and see which values are still guesses.

The standards do not record this. OpenDRIVE and IFC record a source for a whole element or object. Overture records a source for
each value, but not how the value was found. The comparison is in [The format and the standards](standards.md).

## Accuracy (planned)

Each source has its own error. The city's records say for each dataset whether its positions are surveyed or approximate. LiDAR
measures a height to about 0.1 m. Mapillary's positions lie a median 6 m from the city's surveyed poles. OpenStreetMap gives no
accuracy at all. The format will record the
accuracy of every value beside its source (requirement R8 in [The format](../design/format.md)).

## Better values from the connections between sources (planned)

The sources overlap, and the street has rules that must hold: the lanes and sidewalks fill the width between the building lines, a
kerb touches the lane and the sidewalk, a lamp stands on the sidewalk. Each rule is one more measurement.

Take a lamp from the city's survey, accurate to a few centimeters, that lands in the middle of a lane drawn from OpenStreetMap,
accurate to a few metres. The rule "a lamp stands on the sidewalk" is broken, and the less accurate value is the one to move: the lane's edge, not
the lamp. Solved together for a whole area, as surveyors adjust a network of measurements, every value comes closer to the truth,
and its stated accuracy becomes smaller. A rule that cannot hold at all points to a gross error, such as a lamp mapped on the wrong
street. This is on the [roadmap](../plan.md).
