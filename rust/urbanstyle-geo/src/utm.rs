//! WGS84 longitude and latitude to UTM metres (the Transverse Mercator series of Krueger, in the form of Karney 2011, to the sixth power of
//! the third flattening: millimetres over a whole zone). The Python reference reads the same through PROJ (`ST_Transform` to EPSG:326xx).

const A: f64 = 6_378_137.0;
const F: f64 = 1.0 / 298.257_223_563;
const K0: f64 = 0.9996;

/// The UTM zone (1 to 60) of a longitude in degrees.
pub fn zone_of(lon: f64) -> u32 {
    (((lon + 180.0) / 6.0).floor() as i64).rem_euclid(60) as u32 + 1
}

/// Easting and northing in metres of a point, in `zone` (north of the equator).
pub fn forward(lon: f64, lat: f64, zone: u32) -> (f64, f64) {
    let n = F / (2.0 - F);
    let e = (F * (2.0 - F)).sqrt();
    let (n2, n3, n4, n5, n6) = (n * n, n * n * n, n.powi(4), n.powi(5), n.powi(6));
    let big_a = A / (1.0 + n) * (1.0 + n2 / 4.0 + n4 / 64.0 + n6 / 256.0);
    let alpha = [
        n / 2.0 - 2.0 / 3.0 * n2 + 5.0 / 16.0 * n3 + 41.0 / 180.0 * n4 - 127.0 / 288.0 * n5 + 7891.0 / 37800.0 * n6,
        13.0 / 48.0 * n2 - 3.0 / 5.0 * n3 + 557.0 / 1440.0 * n4 + 281.0 / 630.0 * n5 - 1_983_433.0 / 1_935_360.0 * n6,
        61.0 / 240.0 * n3 - 103.0 / 140.0 * n4 + 15061.0 / 26880.0 * n5 + 167_603.0 / 181_440.0 * n6,
        49561.0 / 161_280.0 * n4 - 179.0 / 168.0 * n5 + 6_601_661.0 / 7_257_600.0 * n6,
        34729.0 / 80640.0 * n5 - 3_418_889.0 / 1_995_840.0 * n6,
        212_378_941.0 / 319_334_400.0 * n6,
    ];
    let lon0 = ((zone as f64) - 1.0) * 6.0 - 180.0 + 3.0;
    let (phi, lam) = (lat.to_radians(), (lon - lon0).to_radians());
    let s = phi.sin();
    let t = (s.atanh() - e * (e * s).atanh()).sinh();
    let xi0 = (t / lam.cos()).atan();
    let eta0 = (lam.sin() / (1.0 + t * t).sqrt()).atanh();
    let (mut xi, mut eta) = (xi0, eta0);
    for (j, a) in alpha.iter().enumerate() {
        let k = 2.0 * (j as f64 + 1.0);
        xi += a * (k * xi0).sin() * (k * eta0).cosh();
        eta += a * (k * xi0).cos() * (k * eta0).sinh();
    }
    (500_000.0 + K0 * big_a * eta, K0 * big_a * xi)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn known_points() {
        assert_eq!(zone_of(7.42), 32);
        // the central meridian of zone 32 at the equator
        let (x, y) = forward(9.0, 0.0, 32);
        assert!((x - 500_000.0).abs() < 1e-6 && y.abs() < 1e-6);
        // (the corners of Monaco's boundary against PROJ: urbanstyle-simready/tests/blocks_read.rs, 4 nm)
    }
}
