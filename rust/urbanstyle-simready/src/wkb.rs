//! Well-known binary (what SimReady's and duckOSM's Parquet files hold in their geometry columns), read as `geo` types. Only x and y are
//! kept: the heights of SimReady's lines are the levels' business, not the plan's.
use geo::{Coord, LineString, MultiPolygon, Polygon};

pub enum Geom {
    Point(Coord<f64>),
    Lines(Vec<LineString<f64>>),
    Polys(MultiPolygon<f64>),
}

struct Cur<'a> {
    b: &'a [u8],
    p: usize,
}

impl Cur<'_> {
    fn u32(&mut self, le: bool) -> Option<u32> {
        let x: [u8; 4] = self.b.get(self.p..self.p + 4)?.try_into().ok()?;
        self.p += 4;
        Some(if le { u32::from_le_bytes(x) } else { u32::from_be_bytes(x) })
    }
    fn f64(&mut self, le: bool) -> Option<f64> {
        let x: [u8; 8] = self.b.get(self.p..self.p + 8)?.try_into().ok()?;
        self.p += 8;
        Some(if le { f64::from_le_bytes(x) } else { f64::from_be_bytes(x) })
    }
    fn coords(&mut self, le: bool, dims: usize) -> Option<LineString<f64>> {
        let n = self.u32(le)? as usize;
        let mut v = Vec::with_capacity(n);
        for _ in 0..n {
            let (x, y) = (self.f64(le)?, self.f64(le)?);
            for _ in 2..dims {
                self.f64(le)?;
            }
            v.push(Coord { x, y });
        }
        Some(LineString::new(v))
    }
    fn polygon(&mut self, le: bool, dims: usize) -> Option<Polygon<f64>> {
        let n = self.u32(le)? as usize;
        let mut rings = Vec::with_capacity(n);
        for _ in 0..n {
            rings.push(self.coords(le, dims)?);
        }
        let mut it = rings.into_iter();
        Some(Polygon::new(it.next()?, it.collect()))
    }
    /// One geometry, with its byte order and type; the parts of a multi-geometry are added to `out`.
    fn geom(&mut self, out: &mut Vec<Geom>) -> Option<()> {
        let le = *self.b.get(self.p)? == 1;
        self.p += 1;
        let raw = self.u32(le)?;
        // (ISO codes add 1000 for z, 2000 for m; the EWKB flags are the high bits)
        let (iso, flags) = (raw & 0x0fff_ffff, raw);
        let dims = 2 + usize::from(iso / 1000 == 1 || iso / 1000 == 3 || flags & 0x8000_0000 != 0) + usize::from(iso / 1000 >= 2 || flags & 0x4000_0000 != 0);
        if flags & 0x2000_0000 != 0 {
            self.u32(le)?; // the SRID
        }
        match iso % 1000 {
            1 => {
                let (x, y) = (self.f64(le)?, self.f64(le)?);
                for _ in 2..dims {
                    self.f64(le)?;
                }
                out.push(Geom::Point(Coord { x, y }));
            }
            2 => out.push(Geom::Lines(vec![self.coords(le, dims)?])),
            3 => out.push(Geom::Polys(MultiPolygon::new(vec![self.polygon(le, dims)?]))),
            4..=7 => {
                for _ in 0..self.u32(le)? {
                    self.geom(out)?;
                }
            }
            _ => return None,
        }
        Some(())
    }
}

/// The geometry in `b`. A multi-geometry, or a collection of one kind, is one value; a collection of mixed kinds gives `None`.
pub fn parse(b: &[u8]) -> Option<Geom> {
    let mut parts = Vec::new();
    Cur { b, p: 0 }.geom(&mut parts)?;
    let mut it = parts.into_iter();
    match it.next()? {
        Geom::Point(c) => Some(Geom::Point(c)),
        Geom::Lines(mut l) => {
            for x in it {
                match x {
                    Geom::Lines(m) => l.extend(m),
                    _ => return None,
                }
            }
            Some(Geom::Lines(l))
        }
        Geom::Polys(mut p) => {
            for x in it {
                match x {
                    Geom::Polys(m) => p.0.extend(m.0),
                    _ => return None,
                }
            }
            Some(Geom::Polys(p))
        }
    }
}

pub fn line(b: &[u8]) -> Option<LineString<f64>> {
    match parse(b)? {
        Geom::Lines(mut l) if l.len() == 1 => l.pop(),
        _ => None,
    }
}

pub fn lines(b: &[u8]) -> Option<Vec<LineString<f64>>> {
    match parse(b)? {
        Geom::Lines(l) => Some(l),
        _ => None,
    }
}

pub fn polys(b: &[u8]) -> Option<MultiPolygon<f64>> {
    match parse(b)? {
        Geom::Polys(p) => Some(p),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_line_and_a_polygon() {
        let mut b = vec![1u8];
        b.extend(2u32.to_le_bytes());
        b.extend(2u32.to_le_bytes());
        for v in [1.0f64, 2.0, 3.0, 4.0] {
            b.extend(v.to_le_bytes());
        }
        let l = line(&b).unwrap();
        assert_eq!(l.0, vec![Coord { x: 1.0, y: 2.0 }, Coord { x: 3.0, y: 4.0 }]);
        // the same line with a z (ISO code 1002)
        let mut z = vec![1u8];
        z.extend(1002u32.to_le_bytes());
        z.extend(2u32.to_le_bytes());
        for v in [1.0f64, 2.0, 9.0, 3.0, 4.0, 9.0] {
            z.extend(v.to_le_bytes());
        }
        assert_eq!(line(&z).unwrap(), l);
        let mut p = vec![1u8];
        p.extend(3u32.to_le_bytes());
        p.extend(1u32.to_le_bytes());
        p.extend(4u32.to_le_bytes());
        for v in [0.0f64, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 0.0] {
            p.extend(v.to_le_bytes());
        }
        assert_eq!(polys(&p).unwrap().0.len(), 1);
    }
}
