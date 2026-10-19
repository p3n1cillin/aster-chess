// Aster core. Original attribution and source mapping: timeman.rs.license.
// SPDX-License-Identifier: GPL-3.0-or-later
// Modified 2026-10-19: source naming and notice layout only.

use crate::search::LimitsType;
use crate::types::*;

pub type TimePoint = i64;

pub fn now() -> TimePoint {
    use std::sync::OnceLock;
    use std::time::Instant;
    static START: OnceLock<Instant> = OnceLock::new();
    START.get_or_init(Instant::now).elapsed().as_millis() as TimePoint + 1
}

pub struct TimeManagement {
    pub start_time: TimePoint,
    optimum_time: TimePoint,
    maximum_time: TimePoint,
    pub available_nodes: i64,
    pub use_nodes_time: bool,
}

const NO_BOUND: TimePoint = i64::MAX / 2;

impl Default for TimeManagement {
    fn default() -> Self {
        TimeManagement {
            start_time: 0,
            optimum_time: NO_BOUND,
            maximum_time: NO_BOUND,
            available_nodes: -1,
            use_nodes_time: false,
        }
    }
}

pub struct TmOptions {
    pub nodestime: i64,
    pub move_overhead: i64,
    pub ponder: bool,
}

impl TimeManagement {
    pub fn optimum(&self) -> TimePoint {
        self.optimum_time
    }
    pub fn maximum(&self) -> TimePoint {
        self.maximum_time
    }
    pub fn clear(&mut self) {
        self.available_nodes = -1;
    }
    pub fn advance_nodes_time(&mut self, nodes: i64) {
        self.available_nodes = (self.available_nodes - nodes).max(0);
    }
    pub fn elapsed_time(&self) -> TimePoint {
        now() - self.start_time
    }
    pub fn elapsed(&self, nodes: impl Fn() -> u64) -> TimePoint {
        if self.use_nodes_time {
            nodes() as TimePoint
        } else {
            self.elapsed_time()
        }
    }

    pub fn init(
        &mut self,
        limits: &mut LimitsType,
        us: Color,
        ply: i32,
        opts: &TmOptions,
        original_time_adjust: &mut f64,
    ) {
        let npmsec = opts.nodestime;
        self.start_time = limits.start_time;
        self.use_nodes_time = npmsec != 0;
        if self.use_nodes_time {
            limits.movetime *= npmsec;
        }
        if limits.time[us] == 0 {
            self.optimum_time = NO_BOUND;
            self.maximum_time = NO_BOUND;
            return;
        }
        let mut move_overhead = opts.move_overhead;
        if self.use_nodes_time {
            if self.available_nodes == -1 {
                self.available_nodes = npmsec * limits.time[us];
            }
            limits.time[us] = self.available_nodes;
            limits.inc[us] *= npmsec;
            limits.npmsec = npmsec;
            move_overhead *= npmsec;
        }

        let scale_factor = if self.use_nodes_time { npmsec } else { 1 };
        let scaled_time = (limits.time[us] / scale_factor).max(1);

        let mut mtg = if limits.movestogo != 0 {
            limits.movestogo.min(50)
        } else {
            50
        };
        if scaled_time < 1000 && limits.movestogo == 0 {
            mtg = (scaled_time as f64 * 0.05) as i32;
        }

        let time_left = (limits.time[us] + limits.inc[us] * (mtg as i64 - 1)
            - move_overhead * (2 + mtg as i64))
            .max(1);

        let opt_scale;
        let max_scale;
        if limits.movestogo == 0 {
            if *original_time_adjust < 0.0 {
                *original_time_adjust = 0.3272 * (time_left as f64).log10() - 0.4141;
            }
            let log_time_in_sec = (scaled_time as f64 / 1000.0).log10();
            let opt_constant = (0.0029869 + 0.00033554 * log_time_in_sec).min(0.004905);
            let max_constant = (3.3744 + 3.0608 * log_time_in_sec).max(3.1441);
            opt_scale = (0.012112 + (ply as f64 + 3.22713).powf(0.46866) * opt_constant)
                .min(0.19404 * limits.time[us] as f64 / time_left as f64)
                * *original_time_adjust;
            max_scale = (6.873f64).min(max_constant + ply as f64 / 12.352);
        } else {
            opt_scale = ((0.88 + ply as f64 / 116.4) / mtg as f64)
                .min(0.88 * limits.time[us] as f64 / time_left as f64);
            max_scale = 1.3 + 0.11 * mtg as f64;
        }

        self.optimum_time = (opt_scale * time_left as f64).max(1.0) as TimePoint;
        self.maximum_time = (self.optimum_time as f64).max(
            (0.8097 * limits.time[us] as f64 - move_overhead as f64)
                .min(max_scale * self.optimum_time as f64),
        ) as TimePoint;

        if opts.ponder {
            self.optimum_time += self.optimum_time / 4;
        }
    }
}
