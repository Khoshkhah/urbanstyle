---
hide:
  - toc
---

# The input profile of a bridge

What a bridge profile holds as **input**, with and without LiDAR, what the heights are made from, and where our values stand
against the design standards. The results (one height per node, the slab, the piers) are not inputs; they are described in
[Bridges by rank](bridges-ranks.md).

## The profile file

One file per bridge, `<name>.bridge.json`, written by `urbanstyle bridge` from OSM and duckOSM's lanes (GMNS). Everything in it that
is an input comes from OSM, except the lanes' widths (duckOSM) and, with a survey, the measured heights.

| Input | From | What it is |
|---|---|---|
| axes | OSM | the bridge's roads: each a chain of `bridge=yes` ways, as a line; its start and end are OSM's nodes |
| ends | OSM | for each axis end: on the ground or not (a road that is not a bridge uses the same node) |
| ground points inside an axis | OSM | a node in the middle of an axis that a ground road uses (`ground_at`) |
| crossings | OSM | the points where an axis passes over a road, over a building or over a lower deck |
| sections and bands | duckOSM GMNS | the lanes on each stretch of an axis, their offsets and widths |
| paths | OSM | the footways and cycleways on the bridge, with their widths |
| deck outline | OSM `man_made=bridge` where mapped, else derived from the bands | the structure's edge |
| piers | rule | one every 80 m along an axis where the deck is 3 m or higher (a chosen rule, not a survey) |

**The height inputs are only three kinds.** A ground point: the height is 0 there. A crossing over a road or a building: the deck
must be at least the clearance above it. A crossing of two decks: the upper must be the clearance plus the slab above the lower.

| bridge | ground points | crossings over a road or building | deck over deck | height inputs |
|---|---|---|---|---|
| Granville Bridge | 8 | 0 (water below) | 0 | 8 |
| Avenue de France | 6 | 14 | 3 | 23 |

## Without LiDAR: the rules

The heights of all nodes of a bridge are solved together from the inputs and these rules. Each rule has a value; the table says where
the value comes from and what the design standards say.

| Rule | Our value | The standards | Status |
|---|---|---|---|
| a ground point is at 0 m | hard | by definition | agreed |
| a deck rises from its ground ends at the normal grade, where nothing else decides | 6 % | France (CETU): 6 % at 80 km/h on every road type; Sweden (VGU table 12-1): 6 % on roads, 5 % on walking and cycling ramps; USA (AASHTO, as state manuals quote it): 3 % desirable on freeways, 4 % in tight urban settings, ramps 3 to 5 % | agreed, in the standards |
| the grade along a road is never more than the cap | 18 % | no standard allows it: ramps end at 5 to 8 % | **open**: the cap came from Granville's LiDAR at its ends, not from a standard; 8 % would follow the standards, and a clearance the ramps cannot reach would then be listed, not forced |
| a deck clears a road or a building below | 5.5 m, plus the slab over a deck | France: 4.30 m on all roads, 4.50 m on international routes, 4.75 m on motorways (CETU, PIARC); Sweden (VGU): 4.7 m under a concrete bridge, 5.1 to 5.2 m under a steel bridge; USA (AASHTO): 16 ft = 4.9 m on freeways | agreed; ours is above all three |
| the slab's thickness | 1.8 m | box girders: span / 18 to span / 22 (ASPIRE, PCI); 1.8 m suits a span of 32 to 40 m | **open**: one value for every span; a ramp of 15 m spans is thinner, a 90 m span deeper |
| the deck is never higher than the top | 27 m | no standard; the height of Granville's crest | **open**: a parameter, kept until the clearances decide every crest |
| the smoothest heights among all that keep the rules | the least change of grade | the standards use parabolic vertical curves with a minimum length per design speed (the K value) | agreed in intent; the K values are not applied |
| the parapet | 0.8 m high, 0.3 m wide | traffic barrier TL-4: 36 in = 0.91 m (TxDOT, DelDOT); pedestrians and cyclists: 42 in = 1.07 m, 48 in = 1.2 m where cyclists hit at speed (ADOT, DelDOT) | **open**: ours is below every standard |
| the structure's edge | lanes and paths plus 0.5 m, tapered over 20 m; OSM's outline where mapped | the standards give the lanes' and shoulders' widths; the edge follows them | agreed |

With these inputs and rules alone, Granville has 8 inputs (its 8 ground points) and no crossing: its shape is the 6 % rule up to the
27 m top. Avenue de France has 23 inputs: 19 of its clearances cannot be reached at any allowed grade (Saint-Roman, a hillside the
flat model has no terrain for), and the solve lists them.

## With LiDAR: what changes

A survey (`urbanstyle bridge-measure`, Vancouver's 2022 LiDAR for Granville) adds to the profile, per axis:

| Added | Count on Granville | Used for |
|---|---|---|
| stations every 10 m: deck top, ground, reference ground (3 heights, with the number of returns) | 340 stations | the record of the measurement |
| samples: (distance along the axis, height above the reference ground) | 340 | the record |
| points: the smooth height line fitted through the samples | 82 (3 to 11 per axis) | **the targets the solve holds** |
| landings: how far past OSM's last node the survey saw deck | 5 | nothing in the structure: the start and end of a bridge come from OSM |

So LiDAR changes **heights only**. The solve runs with the same inputs and rules; the 82 points pull it, with a weight, toward the
measured line. It changes no geometry: not the length of a road, not the edge, not the ends. Where a measured height and a rule
disagree (a measured end 2 m above a ground node), the rule holds the node and the slope between them is as steep as the cap allows.

## What comes out

Not inputs: one height per node of the axes (Granville 111, Avenue de France 78), the surface between them, the slab, the sides,
the parapet, the piers. They are the rules' answer to the inputs. The viewer `viz/rank0.html` shows them alone; the checks D1 to D7
test them.

## Decisions to take

1. The grade cap: 8 % as the standards, or keep 18 %.
2. The slab's thickness by span (span / 20), or one value.
3. The parapet's height: 0.9 m for traffic, 1.1 m where a path runs on the deck.
4. The 27 m top: keep as a parameter, or drop it once every crest has a clearance.

## Sources

- France, clearances and grades: [PIARC, tunnels report, chapter 7 (CETU values)](https://tunnels.piarc.org/sites/tunnels/files/public/wysiwyg/import/Chapters%20PIARC%20reports/2001%2005.11.B%20Chap%207%20FR.pdf), [CETU, profil en long](https://www.cetu.developpement-durable.gouv.fr/IMG/pdf/profil_en_long_cle575ce3.pdf), [a course on road clearances (4.30, 4.50, 4.75 m)](https://elearning.univ-eloued.dz/mod/resource/view.php?id=6140)
- Sweden, VGU as projects quote it: [Kungälv, study of a crossing (4.7, 5.1, 5.2 m; 5 % ramps)](https://www.kungalv.se/contentassets/c4407fc10ad04e44ae326127c3dcddcb/granskning2025/studie-gangpassage-marstrandsvagen-2025-handel-vid-e6.pdf), [Norrköping, Riksvägen (6 %, VGU table 12-1)](https://next.norrkoping.se/download/18.37b7ebbe187eae258526641/1684835173014/pm-riksvagen.pdf), [Trafikverket, E4 (4.7 m)](https://bransch.trafikverket.se/contentassets/281b6632c269409e8fa106ac30ca4f44/aktuella/pm_bro.pdf)
- USA, AASHTO as state manuals quote it: [Arizona DOT, SR 303L (ramp grades 3 to 5 %, 16 ft)](https://azdot.gov/sites/default/files/2024-06/Appendix%20A%20-%20303L%20Final%20DCR_AASHTO%20Report.pdf), [Kansas DOT, I-235 (3 %, 4 % urban)](https://ksdot.gov/home/showpublisheddocument/10603)
- Parapets: [TxDOT, minimum railing height](https://www.txdot.gov/manuals/brg/rlg/chapter-4---treatment-of-existing-railing/section-2---bridge-railing-upgrade-requirements/minimum-bridge-railing-height.html), [DelDOT, railings](https://bridgedesignmanual.deldot.gov/index.php/213_-_Railings), [ADOT, railings](https://azdot.gov/sites/default/files/2023-09/Section13-Railings.pdf), [WSDOT, test levels](https://appstest.wsdot.wa.gov/sites/default/files/2022-04/02-2022-Barrier-Test-Level-Modifications.pdf)
- Deck depth: [ASPIRE, concrete segmental bridges, preliminary design](https://www.aspirebridge.com/magazine/2025Winter/CBT-ConcreteSegmentalBridges-PreliminaryDesignApproximations.pdf), [PCI, segmental box girders (1975)](https://pci.org/PCI_Docs/Design_Resources/Guides_and_manuals/references/bridge_design_manual/JL-75-July-August_Tentative_Design_and_Construction_Specifications_for_Precast_Segmental_Box_Girder_Bridges.pdf)
- Vertical curves: [TxDOT, vertical curves](https://www.txdot.gov/manuals/des/rdw/chapter-4--basic-design-criteria/4-8-vertical-alignment/4-8-2-vertical-curves.html) (the K tables themselves are in the AASHTO and TAC guides, not read here)
