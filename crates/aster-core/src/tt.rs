// Aster search cache. Original attribution and source mapping: tt.rs.license.
// SPDX-License-Identifier: GPL-3.0-or-later
// Modified 2026-10-19: typed cache storage and lifetime-checked write leases.

use crate::types::*;
use std::sync::atomic::{AtomicI16, AtomicU8, AtomicU16, Ordering::Relaxed};

const AGE_MASK: u8 = 31;
const WAYS: usize = 3;
const BUCKET_BYTES: usize = 32;

#[derive(Clone, Copy)]
struct Stamp(u8);

impl Stamp {
    #[inline(always)]
    fn encode(generation: u8, bound: Bound, principal: bool) -> Self {
        Self(generation | (bound << 5) | ((principal as u8) << 7))
    }
    #[inline(always)]
    fn age(self, generation: u8) -> u8 {
        generation.wrapping_sub(self.0) & AGE_MASK
    }
    #[inline(always)]
    fn bound(self) -> Bound {
        (self.0 >> 5) & 3
    }
    #[inline(always)]
    fn principal(self) -> bool {
        self.0 & 128 != 0
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct TTData {
    pub mv: Move,
    pub value: Value,
    pub eval: Value,
    pub depth: Depth,
    pub bound: Bound,
    pub is_pv: bool,
}

impl TTData {
    const MISS: Self = Self {
        mv: Move::NONE,
        value: VALUE_NONE,
        eval: VALUE_NONE,
        depth: DEPTH_NONE,
        bound: BOUND_NONE,
        is_pv: false,
    };
}

// Independent relaxed fields deliberately permit mixed snapshots during shared
// search. Search validates score/depth before using such a snapshot.
#[repr(C)]
#[derive(Default)]
struct Slot {
    tag: AtomicU16,
    depth: AtomicU8,
    stamp: AtomicU8,
    best: AtomicU16,
    score: AtomicI16,
    evaluation: AtomicI16,
}

impl Slot {
    #[inline(always)]
    fn snapshot(&self) -> TTData {
        let stamp = Stamp(self.stamp.load(Relaxed));
        TTData {
            mv: Move(self.best.load(Relaxed)),
            value: self.score.load(Relaxed) as Value,
            eval: self.evaluation.load(Relaxed) as Value,
            depth: DEPTH_NONE + self.depth.load(Relaxed) as Depth,
            bound: stamp.bound(),
            is_pv: stamp.principal(),
        }
    }
    #[inline(always)]
    fn occupied(&self) -> bool {
        self.depth.load(Relaxed) != 0
    }
    #[inline(always)]
    fn age(&self, generation: u8) -> u8 {
        Stamp(self.stamp.load(Relaxed)).age(generation)
    }
    fn clear(&self) {
        self.tag.store(0, Relaxed);
        self.depth.store(0, Relaxed);
        self.stamp.store(0, Relaxed);
        self.best.store(0, Relaxed);
        self.score.store(0, Relaxed);
        self.evaluation.store(0, Relaxed);
    }
    #[inline(always)]
    fn reduce_depth(&self, penalty: i32) {
        self.depth.store(
            (self.depth.load(Relaxed) as i32 - penalty).max(0) as u8,
            Relaxed,
        );
    }
    #[allow(clippy::too_many_arguments)]
    #[inline(always)]
    fn store(
        &self,
        key: Key,
        value: Value,
        principal: bool,
        bound: Bound,
        depth: Depth,
        best: Move,
        evaluation: Value,
        generation: u8,
    ) {
        let tag = key as u16;
        if best.is_some() || tag != self.tag.load(Relaxed) {
            self.best.store(best.0, Relaxed);
        }
        if bound == BOUND_EXACT
            || tag != self.tag.load(Relaxed)
            || depth - DEPTH_NONE + 2 * principal as i32 > self.depth.load(Relaxed) as i32 - 4
            || self.age(generation) != 0
        {
            self.tag.store(tag, Relaxed);
            self.depth.store((depth - DEPTH_NONE) as u8, Relaxed);
            self.stamp
                .store(Stamp::encode(generation, bound, principal).0, Relaxed);
            self.score.store(value as i16, Relaxed);
            self.evaluation.store(evaluation as i16, Relaxed);
        } else if self.depth.load(Relaxed) as i32 + DEPTH_NONE >= 5
            && Stamp(self.stamp.load(Relaxed)).bound() != BOUND_EXACT
        {
            let previous = self.score.load(Relaxed) as Value;
            if previous.abs() < VALUE_INFINITE && is_decisive(previous) {
                self.reduce_depth(1);
            }
        }
    }
}

#[repr(C, align(32))]
#[derive(Default)]
struct Bucket {
    slots: [Slot; WAYS],
    padding: [u8; 2],
}
const _: () = assert!(std::mem::size_of::<Slot>() == 10);
const _: () = assert!(std::mem::size_of::<Bucket>() == BUCKET_BYTES);

/// Write lease borrowing its selected slot. Exclusive resize cannot invalidate
/// a live lease through this API.
///
/// ```compile_fail
/// use aster_core::tt::TranspositionTable;
/// let writer = {
///     let table = TranspositionTable::new(1);
///     table.probe(1).2
/// };
/// writer.penalize(1);
/// ```
///
/// ```compile_fail
/// use aster_core::tt::TranspositionTable;
/// let mut table = TranspositionTable::new(1);
/// let writer = table.probe(1).2;
/// table.resize(2);
/// writer.penalize(1);
/// ```
#[derive(Clone, Copy)]
pub struct TTWriter<'cache> {
    slot: &'cache Slot,
}

impl TTWriter<'_> {
    #[allow(clippy::too_many_arguments)]
    #[inline(always)]
    pub fn write(
        &self,
        key: Key,
        value: Value,
        principal: bool,
        bound: Bound,
        depth: Depth,
        best: Move,
        evaluation: Value,
        generation: u8,
    ) {
        self.slot.store(
            key, value, principal, bound, depth, best, evaluation, generation,
        );
    }
    #[inline(always)]
    pub fn penalize(&self, penalty: i32) {
        self.slot.reduce_depth(penalty);
    }
}

/// Fixed associative storage. Atomics supply Send/Sync without manual unsafe
/// marker implementations; borrowing supplies write-handle lifetime checks.
pub struct TranspositionTable {
    buckets: Box<[Bucket]>,
    generation: AtomicU8,
}

impl TranspositionTable {
    pub fn new(mebibytes: usize) -> Self {
        let mut table = Self {
            buckets: Box::default(),
            generation: AtomicU8::new(0),
        };
        table.resize(mebibytes);
        table
    }
    pub fn resize(&mut self, mebibytes: usize) {
        let bytes = mebibytes
            .checked_mul(1024 * 1024)
            .filter(|bytes| *bytes > 0)
            .expect("Cache size must be positive and representable in bytes");
        let count = bytes / BUCKET_BYTES;
        // Drop the old allocation before requesting another large table.
        self.buckets = Box::default();
        self.buckets = (0..count).map(|_| Bucket::default()).collect();
        self.generation.store(0, Relaxed);
    }
    pub fn clear(&self) {
        self.generation.store(0, Relaxed);
        for bucket in &self.buckets {
            for slot in &bucket.slots {
                slot.clear();
            }
        }
    }
    pub fn new_search(&self) {
        let next = self.generation.load(Relaxed).wrapping_add(1) & AGE_MASK;
        self.generation.store(next, Relaxed);
    }
    #[inline(always)]
    pub fn generation(&self) -> u8 {
        self.generation.load(Relaxed)
    }
    pub fn hashfull(&self, max_age: i32) -> i32 {
        let generation = self.generation();
        let occupied = self
            .buckets
            .iter()
            .take(1000)
            .flat_map(|bucket| &bucket.slots)
            .filter(|slot| slot.occupied() && slot.age(generation) as i32 <= max_age)
            .count();
        occupied as i32 / WAYS as i32
    }
    #[inline(always)]
    fn bucket(&self, key: Key) -> &Bucket {
        let index = mul_hi64(key, self.buckets.len() as u64) as usize;
        &self.buckets[index]
    }
    #[inline(always)]
    pub fn prefetch(&self, key: Key) {
        #[cfg(target_arch = "x86_64")]
        unsafe {
            std::arch::x86_64::_mm_prefetch::<{ std::arch::x86_64::_MM_HINT_T0 }>(
                std::ptr::from_ref(self.bucket(key)).cast(),
            );
        }
        #[cfg(not(target_arch = "x86_64"))]
        let _ = key;
    }
    /// Matching tags precede replacement, including unoccupied zero tags.
    /// Replacement ties retain the first slot to preserve search decisions.
    #[inline(always)]
    pub fn probe(&self, key: Key) -> (bool, TTData, TTWriter<'_>) {
        let slots = &self.bucket(key).slots;
        let tag = key as u16;
        for slot in slots {
            if slot.tag.load(Relaxed) == tag {
                return (slot.occupied(), slot.snapshot(), TTWriter { slot });
            }
        }
        let generation = self.generation();
        let mut selected = &slots[0];
        for alternative in &slots[1..] {
            if selected.depth.load(Relaxed) as i32 - 8 * selected.age(generation) as i32
                > alternative.depth.load(Relaxed) as i32 - 8 * alternative.age(generation) as i32
            {
                selected = alternative;
            }
        }
        (false, TTData::MISS, TTWriter { slot: selected })
    }
}

#[cfg(test)]
mod tests;
