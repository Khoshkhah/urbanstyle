# The bridge heights on the area's ground (2026-11-12)

The proposal of this note (a 1 m LiDAR DTM as the area's ground first) is withdrawn. Kaveh's rule: duckOSM's ground is used for a bridge
only at the ground ends of the bridge group, where it gives the ground's z; between the ends the deck comes from urbanstyle's rules. No
LiDAR is needed. The design and the result: `bridge-profile.md`, "The ground at the ends".

Kept from the first study: FABDEM (Monaco's reference ground, 30 m) differs from IGN LiDAR by 4 m to 45 m at several bridge ends
(Boulevard du Larvotto, Avenue Princesse Grace, Boulevard du Ténao, w156780352, w572934026). With the ground read at the ends only, a
deck takes no bump of the grid under it; its ends stand where the area's ground is drawn.
