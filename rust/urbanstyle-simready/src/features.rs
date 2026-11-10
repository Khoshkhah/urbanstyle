//! duckOSM's `features` tables (Parquet files `features-<name>.parquet`, geometry as WKB in longitude and latitude) as the inputs of the
//! `element` step: the buildings, the points of interest inside them, and the off-street car parks (the lots).
use crate::{proj, table::Table, wkb};
use std::collections::BTreeMap;
use std::path::Path;
use urbanstyle_model::elements::{poi_use, BuildingIn, LotIn, PoiIn};

/// The tags the building rules read (`buildings.py`).
const BKEYS: [&str; 7] = ["building:levels", "building:levels:underground", "building:min_level", "height", "location", "building:use", "building"];
/// The tags the rules for a point of interest read.
const PKEYS: [&str; 10] = ["amenity", "shop", "disused:shop", "vacant", "healthcare", "craft", "leisure", "office", "level", "name"];
/// Car parks along the kerb or under a building: no lot of their own (`container.STREET_PARKING` and the covered kinds).
const NOT_LOT: [&str; 9] = ["lane", "street_side", "on_kerb", "half_on_kerb", "shoulder", "layby", "underground", "multi-storey", "rooftop"];

fn subset(t: &BTreeMap<String, String>, keys: &[&str]) -> BTreeMap<String, String> {
    t.iter().filter(|(k, _)| keys.contains(&k.as_str())).map(|(k, v)| (k.clone(), v.clone())).collect()
}

pub fn buildings(path: &Path, zone: u32) -> Result<Vec<BuildingIn>, String> {
    let t = Table::open(path)?;
    let (ty, id, name, kind, tags, geom) = (t.strs("osm_type"), t.i64s("osm_id"), t.strs("name"), t.strs("kind"), t.map_strs("tags"), t.blobs("geom"));
    let mut out = Vec::new();
    for i in 0..id.len() {
        let (Some(id), Some(b)) = (id[i], geom[i].as_ref()) else { continue };
        let Some(wkb::Geom::Polys(m)) = wkb::parse(b) else { continue };
        out.push(BuildingIn {
            osm_type: ty[i].clone().unwrap_or_default(),
            osm_id: id,
            name: name[i].clone(),
            kind: kind[i].clone(),
            tags: subset(&tags[i].clone().unwrap_or_default(), &BKEYS),
            geom: proj::polys(&m, zone),
        });
    }
    Ok(out)
}

/// The points that stand for a business (`buildings.poi_use`).
pub fn pois(path: &Path, zone: u32) -> Result<Vec<PoiIn>, String> {
    let t = Table::open(path)?;
    let (tags, geom) = (t.map_strs("tags"), t.blobs("geom"));
    let mut out = Vec::new();
    for i in 0..tags.len() {
        let Some(wkb::Geom::Point(c)) = geom[i].as_ref().and_then(|b| wkb::parse(b)) else { continue };
        let tg = subset(&tags[i].clone().unwrap_or_default(), &PKEYS);
        if poi_use(&tg).is_some() {
            out.push(PoiIn { tags: tg, point: proj::coord(&c, zone) });
        }
    }
    Ok(out)
}

/// `container.LOTS`: a parking site on the ground that is no car park of the kerb or of a building.
pub fn lots(path: &Path, zone: u32) -> Result<Vec<LotIn>, String> {
    let t = Table::open(path)?;
    let (ty, id, name, kind, tags, geom) = (t.strs("osm_type"), t.i64s("osm_id"), t.strs("name"), t.strs("kind"), t.map_strs("tags"), t.blobs("geom"));
    let mut out = Vec::new();
    for i in 0..id.len() {
        let (Some(id), Some(b)) = (id[i], geom[i].as_ref()) else { continue };
        let tg = tags[i].clone().unwrap_or_default();
        let parking = tg.get("parking").map(String::as_str).unwrap_or("surface");
        if kind[i].as_deref() != Some("parking") || NOT_LOT.contains(&parking) {
            continue;
        }
        let Some(wkb::Geom::Polys(m)) = wkb::parse(b) else { continue };
        let first = ty[i].as_deref().and_then(|s| s.chars().next()).unwrap_or('w');
        out.push(LotIn { id: format!("{first}{id}"), typ: "parking lot".into(), name: name[i].clone(), level: 0, geom: proj::polys(&m, zone) });
    }
    Ok(out)
}

/// The OSM layers that name a surface (`ground.surfaces`): the verges, gardens and play land, the construction sites and the walking ways.
pub struct SurfaceLayers {
    pub verge: Vec<(String, urbanstyle_geo::ops::Mp)>,
    pub garden: Vec<(String, urbanstyle_geo::ops::Mp)>,
    pub play: Vec<(String, urbanstyle_geo::ops::Mp)>,
    pub sites: Vec<(String, urbanstyle_geo::ops::Mp)>,
}

const VERGE_LAND: [&str; 3] = ["grass", "flowerbed", "planting"];
const GARDEN_LAND: [&str; 4] = ["garden", "grass", "allotments", "flowerbed"];
const PLAY_LAND: [&str; 3] = ["playground", "pitch", "dog_park"];

pub fn surface_layers(dir: &Path, zone: u32) -> Result<SurfaceLayers, String> {
    let read = |name: &str| -> Result<Vec<(String, String, urbanstyle_geo::ops::Mp)>, String> {
        let t = Table::open(&dir.join(name))?;
        let (id, kind, geom) = (t.i64s("osm_id"), t.strs("kind"), t.blobs("geom"));
        let mut out = Vec::new();
        for i in 0..id.len() {
            let (Some(id), Some(b)) = (id[i], geom[i].as_ref()) else { continue };
            if let Some(wkb::Geom::Polys(m)) = wkb::parse(b) {
                out.push((format!("w{id}"), kind[i].clone().unwrap_or_default(), proj::polys(&m, zone)));
            }
        }
        Ok(out)
    };
    let (land, sites) = (read("features-land.parquet")?, read("features-sites.parquet")?);
    let of = |rows: &[(String, String, urbanstyle_geo::ops::Mp)], kinds: &[&str]| rows.iter().filter(|r| kinds.contains(&r.1.as_str())).map(|r| (r.0.clone(), r.2.clone())).collect();
    Ok(SurfaceLayers { verge: of(&land, &VERGE_LAND), garden: of(&land, &GARDEN_LAND), play: of(&land, &PLAY_LAND), sites: of(&sites, &["construction"]) })
}
