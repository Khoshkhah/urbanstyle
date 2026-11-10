//! Geometry from longitude and latitude to UTM metres.
use geo::{Coord, LineString, MultiPolygon, Polygon};
use urbanstyle_geo::utm;

pub fn coord(c: &Coord<f64>, zone: u32) -> Coord<f64> {
    let (x, y) = utm::forward(c.x, c.y, zone);
    Coord { x, y }
}

pub fn line(l: &LineString<f64>, zone: u32) -> LineString<f64> {
    LineString::new(l.0.iter().map(|c| coord(c, zone)).collect())
}

pub fn polys(m: &MultiPolygon<f64>, zone: u32) -> MultiPolygon<f64> {
    MultiPolygon::new(m.0.iter().map(|p| Polygon::new(line(p.exterior(), zone), p.interiors().iter().map(|r| line(r, zone)).collect())).collect())
}
