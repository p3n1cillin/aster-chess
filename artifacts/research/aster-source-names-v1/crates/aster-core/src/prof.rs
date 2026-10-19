// Development-only cycle counters (enabled with `--features prof`).

#[cfg(feature = "prof")]
pub mod imp {
    use std::sync::atomic::{AtomicU64, Ordering::Relaxed};
    pub const NAMES: [&str; 11] = [
        "acc_update",
        "ft_transform",
        "layers",
        "movepick",
        "do_move",
        "total_eval",
        "acc_kernel",
        "acc_refresh",
        "fc0",
        "act+fc1",
        "act+fc2",
    ];
    pub static CYCLES: [AtomicU64; 11] = [const { AtomicU64::new(0) }; 11];
    pub static CALLS: [AtomicU64; 11] = [const { AtomicU64::new(0) }; 11];
    #[inline(always)]
    pub fn now() -> u64 {
        unsafe { core::arch::x86_64::_rdtsc() }
    }
    #[inline(always)]
    pub fn add(i: usize, start: u64) {
        CYCLES[i].fetch_add(now() - start, Relaxed);
        CALLS[i].fetch_add(1, Relaxed);
    }
    pub fn report() {
        for i in 0..11 {
            eprintln!(
                "{:>14}: {:>14} cycles {:>10} calls",
                NAMES[i],
                CYCLES[i].load(Relaxed),
                CALLS[i].load(Relaxed)
            );
        }
    }
}

macro_rules! prof_start {
    () => {{
        #[cfg(feature = "prof")]
        {
            crate::prof::imp::now()
        }
        #[cfg(not(feature = "prof"))]
        {
            0u64
        }
    }};
}
macro_rules! prof_end {
    ($i:expr, $s:expr) => {{
        #[cfg(feature = "prof")]
        crate::prof::imp::add($i, $s);
        #[cfg(not(feature = "prof"))]
        let _ = $s;
    }};
}
pub(crate) use {prof_end, prof_start};
