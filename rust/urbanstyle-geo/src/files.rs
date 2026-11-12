//! The input files. The browser has no disk: the page puts each file here first (`put`), and `read` finds it by its path. Natively a path
//! that was not put is read from the disk.
use std::collections::BTreeMap;
use std::path::Path;
use std::sync::{Arc, Mutex};

static FILES: Mutex<BTreeMap<String, Arc<[u8]>>> = Mutex::new(BTreeMap::new());

/// Keep `bytes` as the file `path`.
pub fn put(path: &str, bytes: Vec<u8>) {
    FILES.lock().unwrap().insert(path.to_string(), bytes.into());
}

/// The file `path`: the one that was put, else the one on the disk.
pub fn read(path: &Path) -> std::io::Result<Vec<u8>> {
    if let Some(b) = FILES.lock().unwrap().get(&*path.to_string_lossy()) {
        return Ok(b.to_vec());
    }
    std::fs::read(path)
}

/// As `read`, but a file that was put is removed: a file read once does not stay in memory twice.
pub fn take(path: &Path) -> std::io::Result<Vec<u8>> {
    if let Some(b) = FILES.lock().unwrap().remove(&*path.to_string_lossy()) {
        return Ok(b.to_vec());
    }
    std::fs::read(path)
}
