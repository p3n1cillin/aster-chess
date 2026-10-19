// Copyright (C) 2026 Aster contributors.
// SPDX-License-Identifier: GPL-3.0-or-later

use super::*;

fn store(table: &TranspositionTable, key: Key, depth: Depth, value: Value) {
    table.probe(key).2.write(
        key,
        value,
        false,
        BOUND_LOWER,
        depth,
        Move(123),
        47,
        table.generation(),
    );
}

#[test]
fn packed_metadata_preserves_independent_fields() {
    for generation in 0..=AGE_MASK {
        for bound in 0..=3 {
            for principal in [false, true] {
                let stamp = Stamp::encode(generation, bound, principal);
                assert_eq!(stamp.bound(), bound);
                assert_eq!(stamp.principal(), principal);
                for current in 0..=AGE_MASK {
                    assert_eq!(stamp.age(current), current.wrapping_sub(generation) & 31);
                }
            }
        }
    }
}

#[test]
fn zero_tag_and_hash_extremes_are_valid() {
    let table = TranspositionTable::new(1);
    let (hit, empty, _) = table.probe(0);
    assert!(!hit);
    assert_eq!(empty.value, 0);
    for key in [0, 1, u64::MAX] {
        store(&table, key, 12, -200);
        let (hit, data, _) = table.probe(key);
        assert!(hit);
        assert_eq!(data.value, -200);
        assert_eq!(data.depth, 12);
        assert_eq!(data.eval, 47);
    }
}

#[test]
fn replacement_is_depth_age_ordered_with_stable_ties() {
    let table = TranspositionTable::new(1);
    for key in 1..=3 {
        store(&table, key, 20, key as Value);
    }
    store(&table, 4, 20, 4);
    assert!(!table.probe(1).0);
    assert!(table.probe(2).0 && table.probe(3).0 && table.probe(4).0);
    table.new_search();
    store(&table, 4, 20, 44);
    store(&table, 5, 20, 5);
    assert!(!table.probe(2).0);
    assert!(table.probe(4).0);
}

#[test]
fn shallow_updates_preserve_deep_score_but_can_refresh_move() {
    let table = TranspositionTable::new(1);
    store(&table, 7, 25, 100);
    let (_, _, writer) = table.probe(7);
    writer.write(7, 200, false, BOUND_UPPER, 2, Move(456), 9, 0);
    let data = table.probe(7).1;
    assert_eq!((data.value, data.depth, data.mv), (100, 25, Move(456)));
    writer.write(7, 300, true, BOUND_EXACT, 2, Move::NONE, 10, 0);
    let data = table.probe(7).1;
    assert_eq!((data.value, data.depth, data.mv), (300, 2, Move(456)));
    assert!(data.is_pv);
}

#[test]
fn decisive_aging_penalties_clear_resize_and_wrap() {
    let mut table = TranspositionTable::new(1);
    store(&table, 1, 25, VALUE_MATE - 10);
    table
        .probe(1)
        .2
        .write(1, 5, false, BOUND_UPPER, 1, Move::NONE, 0, 0);
    assert_eq!(table.probe(1).1.depth, 24);
    table.probe(1).2.penalize(1000);
    assert!(!table.probe(1).0);
    for _ in 0..32 {
        table.new_search();
    }
    assert_eq!(table.generation(), 0);
    store(&table, 2, 20, 99);
    table.clear();
    assert!(!table.probe(2).0);
    assert_eq!(table.hashfull(31), 0);
    store(&table, 3, 20, 99);
    table.resize(2);
    assert!(!table.probe(3).0);
    assert_eq!(table.buckets.len(), 2 * 1024 * 1024 / BUCKET_BYTES);
}

#[test]
fn table_and_leases_share_without_manual_marker_implementations() {
    fn shared<T: Send + Sync>() {}
    shared::<TranspositionTable>();
    shared::<TTWriter<'_>>();
    let table = TranspositionTable::new(1);
    std::thread::scope(|scope| {
        for thread in 0..4 {
            let table = &table;
            scope.spawn(move || {
                for index in 1..=1000 {
                    let key = ((thread * 1000 + index) as u64).wrapping_mul(0x9e3779b97f4a7c15);
                    store(table, key, 12, thread);
                    let _ = table.probe(key);
                }
            });
        }
    });
    table.clear();
    assert_eq!(table.hashfull(31), 0);
}

#[test]
#[should_panic(expected = "Cache size must be positive")]
fn zero_capacity_is_rejected_before_lookup() {
    let _ = TranspositionTable::new(0);
}
