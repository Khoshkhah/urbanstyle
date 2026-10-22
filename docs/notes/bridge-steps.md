# Bridges: the words and the order of the steps

Status: agreed with Kaveh on 2026-10-19. No code is changed for this note. It replaces the order of work in the earlier bridge notes:
where they disagree, this note is right.

## Why this note

On 2026-10-19 the work on the cover changed rank 0, which Kaveh had accepted on 2026-10-18, and we used different words for the
same things. This note gives one word for each thing and one order of steps. Each step is frozen when Kaveh accepts it.

## The words

A **bridge level** (the part of one bridge at one level, 1 or 2) is divided into **branches** and **forks**. Each point of the deck is in
one branch or in one fork, never in two.

| Word | Definition |
|---|---|
| **branch** | One road on the bridge: one centre line from OSM and one width (its lanes and paths, plus the edge). The width does not change inside a branch. A branch begins and ends at a fork or at a bridge end. |
| **fork** | The piece of deck where two or more branches meet and share one deck. Inside it, the width changes from one branch to the others. A merge and a fork are the same piece: seen in one direction of travel it is a fork, in the other a merge. A crossing of two roads at one level is also a fork. |
| **junction node** | An OSM node where three or more road ends meet. The lines of the roads meet there. It is at one end of its fork. |
| **branch point** | Where the deck of one arm of a fork stops touching the decks of the other arms. It is the end of that branch at the fork. It is not the junction node: the lanes can fork long before the decks part. |
| **carriageway pair** | Two one-way roads that leave one junction node side by side: within 14 m of each other over at least 40 m and at least 80 % of the shorter one. A pair is one road: one branch, its centre line midway between the two OSM lines. |
| **bridge end** | The last OSM node of a bridge way. The branch ends there, on the ground. |

A branch is not cut where its lane count changes, where an OSM way ends, or where GMNS starts a new link. Those are only axis sections
inside the branch. Example: a9 drops from 5 to 4 lanes inside its branch; the branch keeps its widest width, and the space of the
dropped lane is paved.

## How the points are found

1. **Junction nodes.** From OSM: each node where three or more road ends meet on the bridge.
2. **Carriageway pairs.** At each junction node, two one-way arms that are a carriageway pair count as one road.
3. **Forks.** A junction node where three or more roads meet (after step 2) is a fork. Where only two meet, the road goes on, and the
   two arms are one branch.
4. **Branch points.** For each arm of a fork, walk along it from the junction node, one metre at a time. At each metre, take the
   arm's cross-section, as wide as its one width. The branch point is the first metre where that cross-section no longer touches the
   decks of the other arms. The **trunk** (the arm on the other side of the node from all the others) has its branch point at the node.

The width of an arm comes from its lanes (OSM's lane count, GMNS) and the paths beside it (OSM). The lane width (3.25 m by road class)
and a path width with no `width` tag (2 m) are urbanstyle's chosen values, so a branch point depends on them.

### Granville, measured with this rule

10 branches and 4 forks:

| Fork | Its arms | Trunk | Branch points of the other arms |
|---|---|---|---|
| North (n266729860) | a1, a5, a6, a8 | a1 | a5 42 m, a6 38 m, a8 40 m |
| South end of the main span (n13040317836) | a1, a4, a9 | a1 | a4 85 m, a9 85 m |
| West ramps (n414553095) | a4, a2, a7 | a4 | a2 30 m, a7 30 m |
| Connector (n3488072817) | a9, a3, a10 | a9 | a3 44 m, a10 43 m |

The Hemlock node (n2625030369) is not a fork: a11 and a12 are a carriageway pair, so only two roads meet there. a10, a11 and a12 are
one branch. The branches: a1, a2, a3, a4, a5, a6, a7, a8, a9, and a10+a11+a12.

## Step 2: the shape of a fork

A fork is one straight-sided piece for each arm: from the trunk's cross-section at the junction node to that arm's cross-section at its
branch point (the convex hull of the two cross-sections). The arms' own strips begin at their branch points. So the deck changes width
evenly between the node and the branch points, and it has no bump where the arms' strips would lie wider or narrower than the trunk.

## Step 3: the one width of a branch

A branch has one width and one position. Both come from all the branch's bands (step 4): the lanes SUMO makes on its OSM ways, and the
OSM paths whose edge is within 3 m of the lanes or of a path that already counts.

A path counts in a branch's width only where this branch's lanes are the nearest lanes to it, whichever axis the path was given to,
and only over a stretch of 12 m or more beside them. No chain goes through another road's path. A path in a gore belongs to the road
whose lanes are nearer; a touch of a few metres at a gore tip counts for neither road (Granville: a4 27.3 m → 16.6 m, a6 19.5 m →
14.7 m, a9 19.4 m → 26.3 m).

- **The centre line** is OSM's line, smoothed: each point is the mean of the line within 10 m on each side, and the ends stay where OSM
  puts them. There is no kink at an OSM point.
- **The offset** is one constant for the whole branch: the middle of the bands' overall reach to the left and right of the centre line.
- **The width** holds every band from that offset, plus 0.5 m of edge on each side.
- So the two edges are clean curves parallel to the smooth centre line. A carriageway pair has one strip per carriageway.

## Step 3b: the corners at a fork

Each corner where a fork's straight side meets a branch's edge is rounded with a short fillet: a quadratic curve over 8 m on each side
of the corner. Only corners that turn between 4° and 35° are rounded. The corners near a bridge end (within 16 m) stay square, and so
does the tip of a gore between two arms (it turns more than 35°). The rest of the outline keeps its own points.

## Step 6, rule 1: the pedestrian realm

As on the ground, the pedestrian realm fills the deck from the lanes (or the barrier) to the parapet beside a path. OSM's sidewalk and
cycleway bands of step 4 lie inside it. It is the part of the deck that is nearer to a path than to a lane (measured to 0.5 m, up to
30 m from the path), with its edge rounded over 1 m. A side of a road with no OSM path stays paved. A gore between a road with a path
and a road without one is divided where the two distances are the same.

## Step 6, rule 2: a straight-on connector is a lane

A SUMO connector that turns 30° or less goes straight on. It is drawn as a lane on the axis of the lane it comes from, so the lane
lines, the centre line and the arrows go through it. Only a connector that turns more is a junction lane with a guide line. On
Granville every connector turns 27° or less, so the bridge has no junction lane. The lane lines are drawn along the shared edge of
two lanes of one direction of travel; a hairline gap between two lanes (under 0.1 m) does not stop them.

## Rule 3: a short sideways path piece is a link

An OSM path piece shorter than 12 m that runs at more than 30° to its axis is a **path link** (for example, from a sidewalk to the cycle
path, or to a crossing). It is not a band of the branch's width (step 3), so it makes no bump in the outline (step 3b). The cover
draws it inside the pedestrian realm, cut at the deck's edge (step 6). Granville has six: on a1, a3, a5, a6 and two on a8. The deck
is 58,155 m² (60,924 m² before).

## The order of the steps

Steps 1 to 4 are in 2D, and they are most of the work. Each one is checked on a fast 2D page first. After step 4, and before any 3D,
the bridge gets a 2D dashboard (step 4b).

| Step | What | View | It gives |
|---|---|---|---|
| 1 | Junction nodes, carriageway pairs, forks, branch points | 2D | the points |
| 2 | Branches and forks | 2D | the partition of each bridge level |
| 3 | The centre line (OSM's own line, not smoothed; a carriageway pair on its two OSM lines) and the one width of each branch, placed about its bands' middle ("Step 3: the one width of a branch") | 2D | the branch geometry |
| 3b | Smoothing: the branch lines and edges made smooth, with no jog at an OSM vertex and no step where widths meet (Kaveh, 2026-10-19: "smoothing is the next step") | 2D | smooth branch geometry |
| 4 | The bands of each branch (lanes and paths), joined band by band through each fork, smoothly | 2D | the plan of the cover |
| 4b | A 2D dashboard of the bridge: steps 1 to 4 on the map, before any 3D (Kaveh, 2026-10-19) | 2D | the 2D review page |
| 5 | Rank 0: the outline (the union of the branches and forks of steps 2 to 4), the height surface, the slab, the parapet, the piers | 3D | the structure |
| 6 | The cover: the bands of step 4 laid on the height surface, with barriers and paint | 3D | the cover |
| 7 | The dashboard of the area | 2D and 3D | the page |

Rank 0 comes before the cover in 3D, because the cover lies on the structure and reads its heights. The rank-0 outline needs no rule
of its own: it is the result of steps 2 to 4.

## How a step is frozen

1. The step is shown on its 2D page (or in 3D for steps 5 to 7), and Kaveh reviews it.
2. When Kaveh accepts it, it is committed, and its result is saved as a reference file with a test that fails when the result changes.
3. A later step only reads the earlier steps. It does not change them.
4. An accepted step is changed only when Kaveh asks for it by name. Then its reference is saved again.

## The code today, against these steps

Nothing is frozen yet. What exists:

- Steps 1 and 2: `bridge_surface._branches` and `_merge_carriageways` chain the axes, but they do not find forks or branch points as
  defined here.
- Step 3: `_branches` gives a centre line (OSM, smoothed over 12 m) and one width per branch.
- Step 4: `bridge_cover.layout` lays the lanes (SUMO's cuts, the trunk keeps its lanes at a fork, carriageway pairs) and the path bands
  (OSM). Its fast 2D page is `bridge_cover.plan2d` (`viz/cover2d-granville.html`).
- Step 5: `bridge_surface.model` (the height solve). Today its outline comes from the cover (`bridge_cover.layout`), not from steps 2
  to 4. The outline accepted on 2026-10-18 is kept in `viz/rank0-accepted.bridge3d.json`.
- Step 6: `bridge_cover.layout` and `bridge_surface.model`.
