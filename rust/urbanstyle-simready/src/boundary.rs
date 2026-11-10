//! The area: duckOSM's boundary polygon (`boundary_main.parquet`, longitude and latitude) in UTM metres.
use crate::{table::Table, wkb};
use geo::{Coord, LineString, MultiPolygon, Polygon};
use std::path::Path;
use urbanstyle_geo::utm;

/// The polygons of the file, projected to `zone` (the zone of the mean longitude when `zone` is `None`).
pub fn read(path: &Path, zone: Option<u32>) -> Result<MultiPolygon<f64>, String> {
    let t = Table::open(path)?;
    let mut polys: Vec<Polygon<f64>> = Vec::new();
    for b in t.blobs("geometry").into_iter().flatten() {
        if let Some(wkb::Geom::Polys(m)) = wkb::parse(&b) {
            polys.extend(m.0);
        }
    }
    let pts: Vec<f64> = polys.iter().flat_map(|p| p.exterior().0.iter().map(|c| c.x)).collect();
    let zone = zone.unwrap_or_else(|| utm::zone_of(pts.iter().sum::<f64>() / pts.len().max(1) as f64));
    let ring = |r: &LineString<f64>| LineString::new(r.0.iter().map(|c| { let (x, y) = utm::forward(c.x, c.y, zone); Coord { x, y } }).collect());
    Ok(MultiPolygon::new(polys.iter().map(|p| Polygon::new(ring(p.exterior()), p.interiors().iter().map(ring).collect())).collect()))
}

/// The mean longitude of the boundary's corners, in degrees: the zone of the area comes from it.
pub fn mean_lon(path: &Path) -> Result<f64, String> {
    let t = Table::open(path)?;
    let mut xs: Vec<f64> = Vec::new();
    for b in t.blobs("geometry").into_iter().flatten() {
        if let Some(wkb::Geom::Polys(m)) = wkb::parse(&b) {
            xs.extend(m.0.iter().flat_map(|p| p.exterior().0.iter().map(|c| c.x)));
        }
    }
    Ok(xs.iter().sum::<f64>() / xs.len().max(1) as f64)
}
