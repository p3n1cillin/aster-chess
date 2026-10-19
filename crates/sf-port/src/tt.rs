// Rust port of Stockfish 19 `tt.h/.cpp`.
// Copyright (C) 2004-2026 The Stockfish developers (see AUTHORS file)
// Licensed under the GNU General Public License v3 or later.
//
// Entries use relaxed atomics so racy multi-threaded access is defined
// behaviour in Rust; on x86-64 these compile to plain loads and stores.

use crate::types::*;
use std::sync::atomic::{AtomicI16, AtomicU8, AtomicU16, Ordering::Relaxed};

const GENERATION_BITS: u8 = 5;
const GENERATION_MASK: u8 = (1 << GENERATION_BITS) - 1;
const BOUND_SHIFT: u8 = GENERATION_BITS;
const BOUND_MASK: u8 = 0b11 << BOUND_SHIFT;
const PV_SHIFT: u8 = BOUND_SHIFT + 2;
const PV_MASK: u8 = 1 << PV_SHIFT;

#[derive(Copy, Clone)]
pub struct TTData {
    pub mv: Move,
    pub value: Value,
    pub eval: Value,
    pub depth: Depth,
    pub bound: Bound,
    pub is_pv: bool,
}

#[repr(C)]
#[derive(Default)]
pub struct TTEntry {
    key16: AtomicU16,
    depth8: AtomicU8,
    gen_bound8: AtomicU8,
    move16: AtomicU16,
    value16: AtomicI16,
    eval16: AtomicI16,
}

impl TTEntry {
    #[inline(always)]
    fn read(&self) -> TTData {
        let gb = self.gen_bound8.load(Relaxed);
        TTData {
            mv: Move(self.move16.load(Relaxed)),
            value: self.value16.load(Relaxed) as Value,
            eval: self.eval16.load(Relaxed) as Value,
            depth: DEPTH_NONE + self.depth8.load(Relaxed) as Depth,
            bound: (gb & BOUND_MASK) >> BOUND_SHIFT,
            is_pv: gb & PV_MASK != 0,
        }
    }
    #[inline(always)]
    fn is_occupied(&self) -> bool {
        self.depth8.load(Relaxed) != 0
    }
    #[inline(always)]
    fn relative_age(&self, generation: u8) -> u8 {
        generation.wrapping_sub(self.gen_bound8.load(Relaxed)) & GENERATION_MASK
    }

    #[allow(clippy::too_many_arguments)]
    #[inline(always)]
    fn save(&self, k: Key, v: Value, pv: bool, b: Bound, d: Depth, m: Move, ev: Value, generation: u8) {
        let k16 = k as u16;
        // Preserve the old ttmove if we don't have a new one
        if m.is_some() || k16 != self.key16.load(Relaxed) {
            self.move16.store(m.0, Relaxed);
        }
        // Overwrite less valuable entries (cheapest checks first)
        if b == BOUND_EXACT
            || k16 != self.key16.load(Relaxed)
            || d - DEPTH_NONE + 2 * pv as i32 > self.depth8.load(Relaxed) as i32 - 4
            || self.relative_age(generation) != 0
        {
            self.key16.store(k16, Relaxed);
            self.depth8.store((d - DEPTH_NONE) as u8, Relaxed);
            self.gen_bound8.store(generation | (b << BOUND_SHIFT) | ((pv as u8) << PV_SHIFT), Relaxed);
            self.value16.store(v as i16, Relaxed);
            self.eval16.store(ev as i16, Relaxed);
        } else if self.depth8.load(Relaxed) as i32 + DEPTH_NONE >= 5 && (self.gen_bound8.load(Relaxed) & BOUND_MASK) >> BOUND_SHIFT != BOUND_EXACT {
            // Secondary aging. Important for elementary mate finding.
            let v16 = self.value16.load(Relaxed) as Value;
            if v16.abs() < VALUE_INFINITE && is_decisive(v16) {
                self.depth8.store((self.depth8.load(Relaxed) as i32 - 1).max(0) as u8, Relaxed);
            }
        }
    }
}

const CLUSTER_SIZE: usize = 3;

#[repr(C, align(32))]
#[derive(Default)]
pub struct Cluster {
    entry: [TTEntry; CLUSTER_SIZE],
    _padding: [u8; 2],
}

const _: () = assert!(std::mem::size_of::<Cluster>() == 32);

/// Thin handle used to write back into the probed entry.
#[derive(Copy, Clone)]
pub struct TTWriter {
    entry: *const TTEntry,
}

impl TTWriter {
    #[allow(clippy::too_many_arguments)]
    #[inline(always)]
    pub fn write(&self, k: Key, v: Value, pv: bool, b: Bound, d: Depth, m: Move, ev: Value, generation: u8) {
        unsafe { (*self.entry).save(k, v, pv, b, d, m, ev, generation) }
    }
    /// Flag an entry as useless (decrement the stored depth by the penalty)
    #[inline(always)]
    pub fn penalize(&self, penalty: i32) {
        let e = unsafe { &*self.entry };
        e.depth8.store((e.depth8.load(Relaxed) as i32 - penalty).max(0) as u8, Relaxed);
    }
}

pub struct TranspositionTable {
    table: Vec<Cluster>,
    generation8: AtomicU8,
}

unsafe impl Sync for TranspositionTable {}

impl TranspositionTable {
    pub fn new(mb: usize) -> Self {
        let mut tt = TranspositionTable { table: Vec::new(), generation8: AtomicU8::new(0) };
        tt.resize(mb);
        tt
    }

    pub fn resize(&mut self, mb: usize) {
        let cluster_count = mb * 1024 * 1024 / std::mem::size_of::<Cluster>();
        self.table = Vec::new();
        self.table.reserve_exact(cluster_count);
        self.table.resize_with(cluster_count, Default::default);
        self.generation8.store(0, Relaxed);
    }

    pub fn clear(&self) {
        self.generation8.store(0, Relaxed);
        for c in &self.table {
            for e in &c.entry {
                e.key16.store(0, Relaxed);
                e.depth8.store(0, Relaxed);
                e.gen_bound8.store(0, Relaxed);
                e.move16.store(0, Relaxed);
                e.value16.store(0, Relaxed);
                e.eval16.store(0, Relaxed);
            }
        }
    }

    pub fn new_search(&self) {
        let g = self.generation8.load(Relaxed).wrapping_add(1) & GENERATION_MASK;
        self.generation8.store(g, Relaxed);
    }

    #[inline(always)]
    pub fn generation(&self) -> u8 {
        self.generation8.load(Relaxed)
    }

    pub fn hashfull(&self, max_age: i32) -> i32 {
        let g = self.generation();
        let mut cnt = 0;
        for c in self.table.iter().take(1000) {
            for e in &c.entry {
                cnt += (e.is_occupied() && e.relative_age(g) as i32 <= max_age) as i32;
            }
        }
        cnt / CLUSTER_SIZE as i32
    }

    #[inline(always)]
    pub fn first_entry(&self, key: Key) -> *const TTEntry {
        let idx = mul_hi64(key, self.table.len() as u64) as usize;
        unsafe { self.table.get_unchecked(idx).entry.as_ptr() }
    }

    #[inline(always)]
    pub fn prefetch(&self, key: Key) {
        #[cfg(target_arch = "x86_64")]
        unsafe {
            std::arch::x86_64::_mm_prefetch::<{ std::arch::x86_64::_MM_HINT_T0 }>(self.first_entry(key) as *const i8);
        }
    }

    /// Returns (hit, data, writer) for the given key.
    #[inline(always)]
    pub fn probe(&self, key: Key) -> (bool, TTData, TTWriter) {
        let tte = self.first_entry(key);
        let key16 = key as u16;
        let entries = unsafe { std::slice::from_raw_parts(tte, CLUSTER_SIZE) };
        for e in entries {
            if e.key16.load(Relaxed) == key16 {
                return (e.is_occupied(), e.read(), TTWriter { entry: e });
            }
        }
        let g = self.generation();
        let mut replace = &entries[0];
        for e in &entries[1..] {
            if replace.depth8.load(Relaxed) as i32 - 8 * replace.relative_age(g) as i32 > e.depth8.load(Relaxed) as i32 - 8 * e.relative_age(g) as i32 {
                replace = e;
            }
        }
        (false, TTData { mv: Move::NONE, value: VALUE_NONE, eval: VALUE_NONE, depth: DEPTH_NONE, bound: BOUND_NONE, is_pv: false }, TTWriter { entry: replace })
    }
}
