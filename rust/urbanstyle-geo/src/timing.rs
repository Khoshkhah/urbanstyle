//! A timer for development: `URBANSTYLE_TIMING=1` prints the time of each part to stderr. Not built for the browser (`Instant` does not
//! exist there): in the browser `lap` does nothing.
pub struct Lap {
    #[cfg(not(target_arch = "wasm32"))]
    t: std::time::Instant,
    #[cfg(not(target_arch = "wasm32"))]
    c: u64,
    #[allow(dead_code)]
    prefix: &'static str,
}

impl Lap {
    pub fn new(prefix: &'static str) -> Self {
        Lap {
            #[cfg(not(target_arch = "wasm32"))]
            t: std::time::Instant::now(),
            #[cfg(not(target_arch = "wasm32"))]
            c: cpu_ns(),
            prefix,
        }
    }

    #[allow(unused_variables)]
    pub fn lap(&mut self, label: &str) {
        #[cfg(not(target_arch = "wasm32"))]
        {
            if std::env::var("URBANSTYLE_TIMING").is_ok() {
                // (URBANSTYLE_TIMING=cpu: the CPU time of this thread, which a busy machine does not stretch)
                let ms = if std::env::var("URBANSTYLE_TIMING").as_deref() == Ok("cpu") { (cpu_ns() - self.c) as f64 / 1e6 } else { self.t.elapsed().as_secs_f64() * 1000.0 };
                eprintln!("  {}: {label} {:.0} ms", self.prefix, ms);
            }
            self.t = std::time::Instant::now();
            self.c = cpu_ns();
        }
    }
}

/// The nanoseconds this thread has run on a CPU (Linux: the first field of `/proc/thread-self/schedstat`); 0 elsewhere.
#[cfg(not(target_arch = "wasm32"))]
fn cpu_ns() -> u64 {
    std::fs::read_to_string("/proc/thread-self/schedstat").ok().and_then(|s| s.split_whitespace().next().and_then(|x| x.parse().ok())).unwrap_or(0)
}
