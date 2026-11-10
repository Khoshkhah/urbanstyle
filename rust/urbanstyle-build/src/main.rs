//! `urbanstyle-build DIR [PREFIX] [OUT_DIR] [--checks] [--simready DIR --pass0 DIR [--features DIR]]`: the whole build on the fixture files of DIR (`PREFIX` before
//! each name), and its time. With `--simready` (SimReady's Parquet files) and `--pass0` (duckOSM's pass-0 folder) the blocks and the division read
//! their inputs from those tables.
use std::path::Path;

fn count<'a>(it: impl Iterator<Item = &'a str>) -> std::collections::BTreeMap<&'a str, usize> {
    let mut m = std::collections::BTreeMap::new();
    for k in it {
        *m.entry(k).or_default() += 1;
    }
    m
}

fn main() {
    let mut a: Vec<String> = std::env::args().collect();
    let with_checks = a.iter().any(|x| x == "--checks");
    a.retain(|x| x != "--checks");
    let mut flag = |name: &str| -> Option<String> {
        let i = a.iter().position(|x| x == name)?;
        let v = a.get(i + 1).cloned();
        a.drain(i..(i + 2).min(a.len()));
        v
    };
    let features = flag("--features");
    let sources = match (flag("--simready"), flag("--pass0")) {
        (Some(s), Some(p)) => Some(urbanstyle_build::Sources { simready: s.into(), pass0: p.into(), features: features.map(Into::into) }),
        (None, None) => None,
        _ => panic!("--simready and --pass0 go together"),
    };
    let dir = a.get(1).expect("urbanstyle-build DIR [PREFIX] [OUT_DIR] [--checks]");
    let prefix = a.get(2).map(String::as_str).unwrap_or("");
    let start = std::time::Instant::now();
    let out = a.get(3).map(|o| Path::new(o.as_str()));
    let b = urbanstyle_build::run(Path::new(dir), prefix, out, with_checks, sources.as_ref());
    let total: f64 = b.timings.iter().map(|t| t.1).sum();
    for (name, s) in &b.timings {
        println!("{name:24} {s:7.2} s");
    }
    println!("{:24} {total:7.2} s  (wall {:.2} s)", "all", start.elapsed().as_secs_f64());
    println!(
        "{} spaces, {} parts, {} marks, {} ground rows, {} surfaces, {} stretches, {} elements, {} objects, {} things, {} registry rows",
        b.model.spaces.len(), b.model.parts.len(), b.model.marks.len(), b.model.ground.len(), b.surfaces.len(), b.model.stretches.len(), b.elements.len(), b.objects.len(), b.things.len(), b.registry.len()
    );
    println!("spaces by kind: {:?}", count(b.model.spaces.iter().map(|s| s.kind.as_str())));
    println!("stretches by kind: {:?}", count(b.model.stretches.iter().map(|s| s.kind.as_str())));
    println!("rank 1 ground by kind: {:?}", count(b.model.ground.iter().map(|s| s.kind.as_str())));
    println!("surfaces by kind: {:?}", count(b.surfaces.iter().map(|s| s.kind.as_str())));
    for c in &b.checks {
        println!("  {:4} {:5} {:6}", c.id, c.status(), c.count);
    }
}
