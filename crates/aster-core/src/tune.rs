// Aster core: tunable search parameters.
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Each parameter has the upstream reference value and Aster's value. Ordinary
// builds read them as compile-time constants (no cost; `tp!` folds to a literal).
// Builds with the `tune` feature expose every parameter as a UCI spin option so
// SPSA can tune them; `tune-spec` prints them in the tuner's input format.
// Under `upstream-reference` the upstream values are used, so that build stays
// the exact port.

macro_rules! tunables {
    ($( $name:ident = $upstream:literal => $aster:literal, $min:literal ..= $max:literal; )*) => {
        #[allow(non_camel_case_types, clippy::upper_case_acronyms)]
        #[derive(Clone, Copy)]
        #[repr(usize)]
        pub enum P { $($name,)* }

        /// (name, upstream value, Aster value, min, max)
        pub const PARAMS: &[(&str, i32, i32, i32, i32)] =
            &[$((stringify!($name), $upstream, $aster, $min, $max),)*];
    };
}

tunables! {
    RazorMargin = 342 => 342, 150 ..= 600;
    FutMultBase = 45 => 45, 20 ..= 80;
    FutMultDepth = 4 => 4, 0 ..= 10;
    FutMultMax = 85 => 85, 40 ..= 140;
    FutNoTtHit = 20 => 20, 0 ..= 50;
    FutImproving = 2789 => 2789, 1000 ..= 4500;
    FutOppWorsening = 335 => 335, 0 ..= 1000;
    FutReturnBeta = 661 => 661, 300 ..= 1024;
    NmpDepthMargin = 13 => 13, 0 ..= 40;
    NmpImproving = 47 => 47, 0 ..= 120;
    NmpBase = 365 => 365, 100 ..= 700;
    NmpRedBase = 7 => 7, 3 ..= 12;
    NmpEvalDiv = 256 => 256, 100 ..= 500;
    ProbCutMargin = 241 => 241, 100 ..= 400;
    ProbCutImproving = 64 => 64, 0 ..= 150;
    CapFutBase = 234 => 234, 80 ..= 400;
    CapFutLmrDepth = 247 => 247, 100 ..= 400;
    CapFutHist = 134 => 134, 30 ..= 300;
    CapSeeDepth = 177 => 177, 80 ..= 300;
    CapSeeHist = 34 => 34, 0 ..= 80;
    QuietHistPrune = 4136 => 4136, 2000 ..= 7000;
    QuietHistMain = 69 => 69, 20 ..= 120;
    QuietFutLmr = 119 => 119, 50 ..= 200;
    QuietFutAlpha = 90 => 90, 0 ..= 200;
    QuietFutBase = 164 => 164, 50 ..= 300;
    QuietSee = 23 => 23, 8 ..= 50;
    SeBetaBase = 59 => 59, 30 ..= 100;
    SeBetaTtPv = 66 => 66, 0 ..= 130;
    LmrTtPvBase = 3023 => 3023, 1500 ..= 4500;
    LmrTtPvPv = 1004 => 1004, 0 ..= 2000;
    LmrTtPvValue = 885 => 885, 0 ..= 1800;
    LmrTtPvDepth = 816 => 816, 0 ..= 1600;
    LmrTtPvCut = 940 => 940, 0 ..= 1800;
    LmrBase = 697 => 697, 0 ..= 1500;
    LmrMoveCount = 65 => 65, 0 ..= 150;
    LmrCorr = 26310 => 26310, 10000 ..= 50000;
    LmrCutNode = 4026 => 4026, 2500 ..= 5500;
    LmrCutNoTt = 933 => 933, 0 ..= 1800;
    LmrTtCapture = 1079 => 1079, 300 ..= 2000;
    LmrCutoffBase = 264 => 264, 0 ..= 800;
    LmrCutoffMany = 1095 => 1095, 300 ..= 2000;
    LmrCutoffAll = 1138 => 1138, 300 ..= 2000;
    LmrTtMove = 2179 => 2179, 1000 ..= 3500;
    LmrStatDiv = 439 => 439, 200 ..= 800;
    StatCapPiece = 873 => 873, 400 ..= 1400;
    StatMain = 2252 => 2252, 1000 ..= 3500;
    StatCont0 = 1126 => 1126, 500 ..= 2000;
    StatCont1 = 1093 => 1093, 500 ..= 2000;
}

#[cfg(feature = "tune")]
static VALUES: [std::sync::atomic::AtomicI32; PARAMS.len()] = {
    let mut v = [const { std::sync::atomic::AtomicI32::new(0) }; PARAMS.len()];
    let mut i = 0;
    while i < PARAMS.len() {
        v[i] = std::sync::atomic::AtomicI32::new(PARAMS[i].2);
        i += 1;
    }
    v
};

/// Current value of a parameter (tune builds only).
#[cfg(feature = "tune")]
#[inline(always)]
pub fn get(p: P) -> i32 {
    VALUES[p as usize].load(std::sync::atomic::Ordering::Relaxed)
}

/// Sets a parameter by (case-insensitive) name; false if unknown.
#[cfg(feature = "tune")]
pub fn set(name: &str, value: i32) -> bool {
    match PARAMS.iter().position(|p| p.0.eq_ignore_ascii_case(name)) {
        Some(i) => {
            let v = value.clamp(PARAMS[i].3, PARAMS[i].4);
            VALUES[i].store(v, std::sync::atomic::Ordering::Relaxed);
            true
        }
        None => false,
    }
}

/// UCI option lines for every parameter (tune builds only).
#[cfg(feature = "tune")]
pub fn uci_options() -> Vec<String> {
    PARAMS
        .iter()
        .map(|p| {
            format!(
                "option name {} type spin default {} min {} max {}",
                p.0, p.2, p.3, p.4
            )
        })
        .collect()
}

/// Tuner input: `name,int,value,min,max,c_end,r_end` (fishtest SPSA format).
pub fn spec() -> String {
    PARAMS
        .iter()
        .map(|p| {
            let c_end = (((p.4 - p.3) as f64) / 20.0).max(1.0);
            format!("{},int,{},{},{},{:.2},0.0020", p.0, p.2, p.3, p.4, c_end)
        })
        .collect::<Vec<_>>()
        .join("\n")
}

/// A search parameter: the upstream value under `upstream-reference`, Aster's
/// value as a constant in ordinary builds, the live UCI value with `tune`.
macro_rules! tp {
    ($name:ident) => {{
        #[cfg(feature = "tune")]
        let v = $crate::tune::get($crate::tune::P::$name);
        #[cfg(all(not(feature = "tune"), feature = "upstream-reference"))]
        let v = {
            const V: i32 = $crate::tune::PARAMS[$crate::tune::P::$name as usize].1;
            V
        };
        #[cfg(all(not(feature = "tune"), not(feature = "upstream-reference")))]
        let v = {
            const V: i32 = $crate::tune::PARAMS[$crate::tune::P::$name as usize].2;
            V
        };
        v
    }};
}
