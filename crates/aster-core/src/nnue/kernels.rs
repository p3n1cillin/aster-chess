// Aster core. Original attribution and source mapping: kernels.rs.license.
// SPDX-License-Identifier: GPL-3.0-or-later
// Modified 2026-10-19: source naming and notice layout; int8 piece-square rows.

use super::network::{L1, L2};
use std::sync::atomic::{AtomicU8, Ordering::Relaxed};

pub const LEVEL_SCALAR: u8 = 0;
pub const LEVEL_AVX2: u8 = 1;
pub const LEVEL_AVX512: u8 = 2;

static LEVEL: AtomicU8 = AtomicU8::new(LEVEL_SCALAR);
static VBMI2: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

/// Detects CPU features once; `ASTER_SIMD=scalar|avx2` can force a lower level.
pub fn init() {
    #[allow(unused_mut)]
    let mut level = LEVEL_SCALAR;
    #[cfg(target_arch = "x86_64")]
    {
        if is_x86_feature_detected!("avx2") && is_x86_feature_detected!("bmi2") {
            level = LEVEL_AVX2;
        }
        if is_x86_feature_detected!("avx512f")
            && is_x86_feature_detected!("avx512bw")
            && is_x86_feature_detected!("avx512vnni")
        {
            level = LEVEL_AVX512;
            VBMI2.store(is_x86_feature_detected!("avx512vbmi2"), Relaxed);
        }
    }
    match std::env::var("ASTER_SIMD").as_deref() {
        Ok("scalar") => level = LEVEL_SCALAR,
        Ok("avx2") => level = level.min(LEVEL_AVX2),
        _ => {}
    }
    LEVEL.store(level, Relaxed);
}

#[inline(always)]
pub fn level() -> u8 {
    LEVEL.load(Relaxed)
}

pub fn level_name() -> &'static str {
    match level() {
        LEVEL_AVX512 => "avx512-vnni",
        LEVEL_AVX2 => "avx2",
        _ => "scalar",
    }
}

/// Hint the CPU to start loading a weight row (the hardware prefetcher follows).
#[inline(always)]
pub fn prefetch<T>(p: *const T) {
    #[cfg(target_arch = "x86_64")]
    unsafe {
        std::arch::x86_64::_mm_prefetch::<{ std::arch::x86_64::_MM_HINT_T1 }>(p as *const i8);
    }
}

/// Hint the CPU to load a small search-table entry into the L1 cache.
#[inline(always)]
pub fn prefetch_l1<T>(p: *const T) {
    #[cfg(target_arch = "x86_64")]
    unsafe {
        std::arch::x86_64::_mm_prefetch::<{ std::arch::x86_64::_MM_HINT_T0 }>(p as *const i8);
    }
}

/// Number of i32 chunks (4 input bytes) in the fc_0 input.
pub const FC0_CHUNKS: usize = L1 / 4;

/// Experimental transformed input with only its initialized index prefix exposed.
#[cfg(feature = "fused-input")]
#[repr(C, align(64))]
pub(super) struct FusedInput {
    input: [u8; L1],
    indices: [std::mem::MaybeUninit<u16>; FC0_CHUNKS + 32],
    len: usize,
}

#[cfg(feature = "fused-input")]
impl FusedInput {
    #[inline]
    pub fn new(first: &[i16; L1], second: &[i16; L1]) -> Option<Self> {
        #[cfg(target_arch = "x86_64")]
        if level() == LEVEL_AVX512 && VBMI2.load(Relaxed) {
            let mut input = std::mem::MaybeUninit::<[u8; L1]>::uninit();
            let mut indices = [std::mem::MaybeUninit::<u16>::uninit(); FC0_CHUNKS + 32];
            // Dispatch guarantees all required features. The kernel writes every
            // input byte and exactly the returned prefix (plus bounded slack).
            let len = unsafe {
                avx512::transform_sparse(
                    first,
                    second,
                    input.as_mut_ptr().cast(),
                    indices.as_mut_ptr().cast(),
                )
            };
            return Some(Self {
                input: unsafe { input.assume_init() },
                indices,
                len,
            });
        }
        #[cfg(not(target_arch = "x86_64"))]
        let _ = (first, second);
        None
    }

    #[inline]
    pub fn affine(&self, weights: &[i8], output: &mut [i32; L2]) {
        assert_eq!(weights.len(), L1 * L2);
        #[cfg(target_arch = "x86_64")]
        unsafe {
            // Construction guarantees ISA support and initialization. The
            // initialized prefix is never expanded to include scratch slack.
            let indices = std::slice::from_raw_parts(self.indices.as_ptr().cast(), self.len);
            avx512::sparse_affine_fc0_list(&self.input, weights, output, indices);
        }
    }
}

/// Chunked weight layout used by all affine kernels:
/// w[chunk * OUT * 4 + out * 4 + k] = W[out][chunk * 4 + k].
pub fn chunk_layout(w_row_major: &[i8], outs: usize, ins: usize) -> Vec<i8> {
    let mut v = vec![0i8; outs * ins];
    for o in 0..outs {
        for i in 0..ins {
            v[(i / 4) * outs * 4 + o * 4 + (i % 4)] = w_row_major[o * ins + i];
        }
    }
    v
}

// ---------------------------------------------------------------------------
// Accumulator update: dst = src - Σ sub16 + Σ add16 - Σ sub8 + Σ add8
// ---------------------------------------------------------------------------

pub struct Rows<'a> {
    pub sub16: &'a [&'a [i16]],
    pub add16: &'a [&'a [i16]],
    pub sub8: &'a [&'a [i8]],
    pub add8: &'a [&'a [i8]],
}

/// Feature-index form of an accumulator update: rows are `base + index * L1`.
/// Piece-square and threat/pawn-pair rows are both int8.
pub struct IdxRows<'a> {
    pub base_psq: *const i8,
    pub sub_psq: &'a [u16],
    pub add_psq: &'a [u16],
    pub base8: *const i8,
    pub sub8: &'a [u16],
    pub add8: &'a [u16],
}

/// dst = src - Σ psq[sub_psq] + Σ psq[add_psq] - Σ thr[sub8] + Σ thr[add8]
#[inline(always)]
pub fn update_acc_idx(dst: *mut i16, src: *const i16, r: &IdxRows) {
    #[cfg(target_arch = "x86_64")]
    match level() {
        LEVEL_AVX512 => return unsafe { avx512::update_acc_idx(dst, src, r) },
        LEVEL_AVX2 => return unsafe { avx2::update_acc_idx(dst, src, r) },
        _ => {}
    }
    scalar_update_acc_idx(dst, src, r)
}

// Consume the indices directly. In-place refreshes use identical src/dst pointers;
// copy permits this alias, and each row still adds modulo 2^16.
fn scalar_update_acc_idx(dst: *mut i16, src: *const i16, r: &IdxRows) {
    unsafe {
        std::ptr::copy(src, dst, L1);
        for (base, indices, subtract) in [
            (r.base_psq, r.sub_psq, true),
            (r.base_psq, r.add_psq, false),
            (r.base8, r.sub8, true),
            (r.base8, r.add8, false),
        ] {
            for &index in indices {
                let row = base.add(index as usize * L1);
                for j in 0..L1 {
                    let weight = *row.add(j) as i16;
                    let value = &mut *dst.add(j);
                    *value = if subtract {
                        value.wrapping_sub(weight)
                    } else {
                        value.wrapping_add(weight)
                    };
                }
            }
        }
    }
}

/// `src` and `dst` may alias (pass the same pointer for in-place updates).
#[inline(always)]
pub fn update_acc(dst: *mut i16, src: *const i16, rows: &Rows) {
    let t = crate::prof::prof_start!();
    update_acc_impl(dst, src, rows);
    crate::prof::prof_end!(6, t);
}

#[inline(always)]
fn update_acc_impl(dst: *mut i16, src: *const i16, rows: &Rows) {
    #[cfg(target_arch = "x86_64")]
    match level() {
        LEVEL_AVX512 => return unsafe { avx512::update_acc(dst, src, rows) },
        LEVEL_AVX2 => return unsafe { avx2::update_acc(dst, src, rows) },
        _ => {}
    }
    scalar_update_acc(dst, src, rows)
}

fn scalar_update_acc(dst: *mut i16, src: *const i16, rows: &Rows) {
    let mut acc = [0i16; L1];
    unsafe { std::ptr::copy_nonoverlapping(src, acc.as_mut_ptr(), L1) };
    for r in rows.sub16 {
        for j in 0..L1 {
            acc[j] = acc[j].wrapping_sub(r[j]);
        }
    }
    for r in rows.add16 {
        for j in 0..L1 {
            acc[j] = acc[j].wrapping_add(r[j]);
        }
    }
    for r in rows.sub8 {
        for j in 0..L1 {
            acc[j] = acc[j].wrapping_sub(r[j] as i16);
        }
    }
    for r in rows.add8 {
        for j in 0..L1 {
            acc[j] = acc[j].wrapping_add(r[j] as i16);
        }
    }
    unsafe { std::ptr::copy_nonoverlapping(acc.as_ptr(), dst, L1) };
}

/// Bitboard of squares whose piece differs between two 64-byte boards.
#[inline(always)]
pub fn changed_squares(old: &[u8; 64], new: &[u8; 64]) -> u64 {
    #[cfg(target_arch = "x86_64")]
    if level() == LEVEL_AVX512 {
        return unsafe { avx512::changed_squares(old, new) };
    }
    let mut changed = 0u64;
    for sq in 0..64 {
        changed |= ((old[sq] != new[sq]) as u64) << sq;
    }
    changed
}

// ---------------------------------------------------------------------------
// Feature transformer output: pairwise clipped products of one perspective.
// out[j] = clamp(acc[j], 0, 255) * clamp(acc[j + 512], 0, 255) / 512
// ---------------------------------------------------------------------------

#[inline(always)]
pub fn transform_perspective(acc: &[i16; L1], out: &mut [u8]) {
    #[cfg(target_arch = "x86_64")]
    match level() {
        LEVEL_AVX512 => return unsafe { avx512::transform_perspective(acc, out) },
        LEVEL_AVX2 => return unsafe { avx2::transform_perspective(acc, out) },
        _ => {}
    }
    let half = L1 / 2;
    for j in 0..half {
        let s0 = acc[j].clamp(0, 255) as u32;
        let s1 = acc[j + half].clamp(0, 255) as u32;
        out[j] = ((s0 * s1) / 512) as u8;
    }
}

// ---------------------------------------------------------------------------
// fc_0: sparse affine over non-zero 4-byte input chunks.
// ---------------------------------------------------------------------------

#[inline(always)]
pub fn sparse_affine_fc0(input: &[u8; L1], w: &[i8], out: &mut [i32; L2]) {
    #[cfg(target_arch = "x86_64")]
    match level() {
        LEVEL_AVX512 => return unsafe { avx512::sparse_affine_fc0(input, w, out) },
        LEVEL_AVX2 => return unsafe { avx2::sparse_affine_fc0(input, w, out) },
        _ => {}
    }
    for c in 0..FC0_CHUNKS {
        let x = &input[c * 4..c * 4 + 4];
        if x == [0, 0, 0, 0] {
            continue;
        }
        let wc = &w[c * L2 * 4..(c + 1) * L2 * 4];
        for o in 0..L2 {
            let mut s = 0i32;
            for k in 0..4 {
                s += x[k] as i32 * wc[o * 4 + k] as i32;
            }
            out[o] += s;
        }
    }
}

/// fc_1: dense 64 -> 32 affine, chunked weight layout.
#[inline(always)]
pub fn dense_affine_fc1(input: &[u8; 64], w: &[i8], out: &mut [i32; 32]) {
    #[cfg(target_arch = "x86_64")]
    match level() {
        LEVEL_AVX512 => return unsafe { avx512::dense_affine_fc1(input, w, out) },
        LEVEL_AVX2 => return unsafe { avx2::dense_affine_fc1(input, w, out) },
        _ => {}
    }
    for c in 0..16 {
        let x = &input[c * 4..c * 4 + 4];
        let wc = &w[c * 128..(c + 1) * 128];
        for o in 0..32 {
            let mut s = 0i32;
            for k in 0..4 {
                s += x[k] as i32 * wc[o * 4 + k] as i32;
            }
            out[o] += s;
        }
    }
}

/// Squared and linear clipped ReLU of 32 values:
/// out[i] = min(127, x^2 >> (2S + 7)), out[32 + i] = clamp(x >> S, 0, 127).
#[inline(always)]
pub fn activations<const S: u32>(x: &[i32; 32], out: &mut [u8]) {
    #[cfg(target_arch = "x86_64")]
    if level() == LEVEL_AVX512 {
        return unsafe { avx512::activations::<S>(x, out) };
    }
    for i in 0..32 {
        let v = x[i] as i64;
        out[i] = ((v * v) >> (2 * S + 7)).min(127) as u8;
        out[32 + i] = (x[i] >> S).clamp(0, 127) as u8;
    }
}

/// fc_2: single-output dot product over 128 inputs.
#[inline(always)]
pub fn dot128(input: &[u8; 128], w: &[i8; 128]) -> i32 {
    #[cfg(target_arch = "x86_64")]
    if level() == LEVEL_AVX512 {
        return unsafe { avx512::dot128(input, w) };
    }
    let mut s = 0i32;
    for i in 0..128 {
        s += input[i] as i32 * w[i] as i32;
    }
    s
}

#[cfg(test)]
mod indexed_tests {
    use super::*;

    fn exercise(mut kernel: impl FnMut(*mut i16, *const i16, &IdxRows)) {
        const ROWS: usize = 19;
        let mut seed = 0x4a73_985d_23cb_801fu64;
        let mut random = || {
            seed ^= seed << 13;
            seed ^= seed >> 7;
            seed ^= seed << 17;
            seed
        };
        // Deliberately offset byte rows to exercise unaligned AVX2 loads.
        let mut psq = vec![0i8; ROWS * L1 + 1];
        let mut threat = vec![0i8; ROWS * L1 + 1];
        for (p, t) in psq.iter_mut().zip(threat.iter_mut()) {
            *p = random() as i8;
            *t = (random() >> 32) as i8;
        }
        psq[1..5].copy_from_slice(&[i8::MIN, i8::MAX, -1, 0]);
        threat[1..5].copy_from_slice(&[i8::MAX, i8::MIN, 1, 0]);
        for case in 0..128 {
            let mut source = [0i16; L1];
            for v in &mut source {
                *v = random() as i16;
            }
            source[..4].copy_from_slice(&[i16::MIN, i16::MAX, -1, 0]);
            let mut lists: [Vec<u16>; 4] = std::array::from_fn(|_| Vec::new());
            for list in &mut lists {
                for _ in 0..random() % 33 {
                    list.push((random() % ROWS as u64) as u16);
                }
            }
            match case {
                0 => lists.iter_mut().for_each(Vec::clear),
                1 => lists = std::array::from_fn(|_| vec![0; 32]),
                2 => lists = [vec![0; 32], vec![], vec![], vec![]],
                3 => lists = [vec![], vec![], vec![], vec![0; 32]],
                4 => lists = [vec![18, 0, 18], vec![18, 0, 18], vec![1], vec![1]],
                _ => {}
            }
            // Independent wide-sum oracle, narrowing only once per lane.
            let expected: [i16; L1] = std::array::from_fn(|j| {
                let mut value = source[j] as i64;
                for (n, list) in lists.iter().enumerate() {
                    let weights = if n < 2 { &psq } else { &threat };
                    let sign = if n % 2 == 0 { -1 } else { 1 };
                    for &index in list {
                        value += sign * weights[1 + index as usize * L1 + j] as i64;
                    }
                }
                value as i16
            });
            let rows = IdxRows {
                base_psq: unsafe { psq.as_ptr().add(1) },
                sub_psq: &lists[0],
                add_psq: &lists[1],
                base8: unsafe { threat.as_ptr().add(1) },
                sub8: &lists[2],
                add8: &lists[3],
            };
            let mut separate = [123i16; L1];
            kernel(separate.as_mut_ptr(), source.as_ptr(), &rows);
            assert_eq!(separate, expected, "separate case {case}");
            let mut in_place = source;
            let p = in_place.as_mut_ptr();
            kernel(p, p, &rows);
            assert_eq!(in_place, expected, "in-place case {case}");
        }
    }

    #[test]
    fn scalar_indexed_updates_match_wide_oracle_with_wrapping_and_aliasing() {
        exercise(scalar_update_acc_idx);
    }

    #[test]
    #[cfg(target_arch = "x86_64")]
    fn avx2_indexed_updates_match_wide_oracle_with_wrapping_and_aliasing() {
        if is_x86_feature_detected!("avx2") {
            exercise(|dst, src, rows| unsafe { avx2::update_acc_idx(dst, src, rows) });
        }
    }
}

#[cfg(target_arch = "x86_64")]
mod avx512 {
    use super::*;
    use std::arch::x86_64::*;

    const TILE: usize = 512; // i16 lanes per tile (16 zmm registers)
    const REGS: usize = TILE / 32;

    #[target_feature(enable = "avx512f,avx512bw")]
    pub unsafe fn update_acc(dst: *mut i16, src: *const i16, rows: &Rows) {
        unsafe {
            for t in 0..L1 / TILE {
                let base = t * TILE;
                let mut acc = [_mm512_setzero_si512(); REGS];
                for k in 0..REGS {
                    acc[k] = _mm512_loadu_si512(src.add(base + k * 32) as *const _);
                }
                for r in rows.sub16 {
                    let p = r.as_ptr().add(base);
                    for k in 0..REGS {
                        acc[k] =
                            _mm512_sub_epi16(acc[k], _mm512_loadu_si512(p.add(k * 32) as *const _));
                    }
                }
                for r in rows.add16 {
                    let p = r.as_ptr().add(base);
                    for k in 0..REGS {
                        acc[k] =
                            _mm512_add_epi16(acc[k], _mm512_loadu_si512(p.add(k * 32) as *const _));
                    }
                }
                for r in rows.sub8 {
                    let p = r.as_ptr().add(base);
                    for k in 0..REGS {
                        let w = _mm512_cvtepi8_epi16(_mm256_loadu_si256(p.add(k * 32) as *const _));
                        acc[k] = _mm512_sub_epi16(acc[k], w);
                    }
                }
                for r in rows.add8 {
                    let p = r.as_ptr().add(base);
                    for k in 0..REGS {
                        let w = _mm512_cvtepi8_epi16(_mm256_loadu_si256(p.add(k * 32) as *const _));
                        acc[k] = _mm512_add_epi16(acc[k], w);
                    }
                }
                for k in 0..REGS {
                    _mm512_storeu_si512(dst.add(base + k * 32) as *mut _, acc[k]);
                }
            }
        }
    }

    #[target_feature(enable = "avx512f,avx512bw")]
    pub unsafe fn update_acc_idx(dst: *mut i16, src: *const i16, r: &IdxRows) {
        unsafe {
            for t in 0..L1 / TILE {
                let base = t * TILE;
                let mut acc = [_mm512_setzero_si512(); REGS];
                for k in 0..REGS {
                    acc[k] = _mm512_loadu_si512(src.add(base + k * 32) as *const _);
                }
                for &i in r.sub_psq {
                    let p = r.base_psq.add(i as usize * L1 + base);
                    for k in 0..REGS {
                        let w = _mm512_cvtepi8_epi16(_mm256_load_si256(p.add(k * 32) as *const _));
                        acc[k] = _mm512_sub_epi16(acc[k], w);
                    }
                }
                for &i in r.add_psq {
                    let p = r.base_psq.add(i as usize * L1 + base);
                    for k in 0..REGS {
                        let w = _mm512_cvtepi8_epi16(_mm256_load_si256(p.add(k * 32) as *const _));
                        acc[k] = _mm512_add_epi16(acc[k], w);
                    }
                }
                for &i in r.sub8 {
                    let p = r.base8.add(i as usize * L1 + base);
                    for k in 0..REGS {
                        let w = _mm512_cvtepi8_epi16(_mm256_load_si256(p.add(k * 32) as *const _));
                        acc[k] = _mm512_sub_epi16(acc[k], w);
                    }
                }
                for &i in r.add8 {
                    let p = r.base8.add(i as usize * L1 + base);
                    for k in 0..REGS {
                        let w = _mm512_cvtepi8_epi16(_mm256_load_si256(p.add(k * 32) as *const _));
                        acc[k] = _mm512_add_epi16(acc[k], w);
                    }
                }
                for k in 0..REGS {
                    _mm512_storeu_si512(dst.add(base + k * 32) as *mut _, acc[k]);
                }
            }
        }
    }

    #[target_feature(enable = "avx512f,avx512bw")]
    pub unsafe fn changed_squares(old: &[u8; 64], new: &[u8; 64]) -> u64 {
        unsafe {
            let a = _mm512_loadu_si512(old.as_ptr() as *const _);
            let b = _mm512_loadu_si512(new.as_ptr() as *const _);
            _mm512_cmpneq_epi8_mask(a, b)
        }
    }

    #[target_feature(enable = "avx512f,avx512bw")]
    pub unsafe fn transform_perspective(acc: &[i16; L1], out: &mut [u8]) {
        unsafe {
            let half = L1 / 2;
            let zero = _mm512_setzero_si512();
            let ftmax = _mm512_set1_epi16(255);
            let fix = _mm512_setr_epi64(0, 2, 4, 6, 1, 3, 5, 7);
            let a = acc.as_ptr();
            for j in (0..half).step_by(64) {
                let a0 = _mm512_loadu_si512(a.add(j) as *const _);
                let a1 = _mm512_loadu_si512(a.add(j + 32) as *const _);
                let b0 = _mm512_loadu_si512(a.add(half + j) as *const _);
                let b1 = _mm512_loadu_si512(a.add(half + j + 32) as *const _);
                let s0 =
                    _mm512_slli_epi16::<7>(_mm512_max_epi16(_mm512_min_epi16(a0, ftmax), zero));
                let s1 =
                    _mm512_slli_epi16::<7>(_mm512_max_epi16(_mm512_min_epi16(a1, ftmax), zero));
                let p0 = _mm512_mulhi_epi16(s0, _mm512_min_epi16(b0, ftmax));
                let p1 = _mm512_mulhi_epi16(s1, _mm512_min_epi16(b1, ftmax));
                let packed = _mm512_permutexvar_epi64(fix, _mm512_packus_epi16(p0, p1));
                _mm512_storeu_si512(out.as_mut_ptr().add(j) as *mut _, packed);
            }
        }
    }

    // Consume each pair before writing it, preserving the old compression order.
    #[cfg(feature = "fused-input")]
    #[target_feature(enable = "avx512f,avx512bw,avx512vbmi2")]
    pub(super) unsafe fn transform_sparse(
        first: &[i16; L1],
        second: &[i16; L1],
        output: *mut u8,
        indices: *mut u16,
    ) -> usize {
        unsafe {
            let zero = _mm512_setzero_si512();
            let maximum = _mm512_set1_epi16(255);
            let fix = _mm512_setr_epi64(0, 2, 4, 6, 1, 3, 5, 7);
            let mut index = _mm512_set_epi16(
                31, 30, 29, 28, 15, 14, 13, 12, 27, 26, 25, 24, 11, 10, 9, 8, 23, 22, 21, 20, 7, 6,
                5, 4, 19, 18, 17, 16, 3, 2, 1, 0,
            );
            let step = _mm512_set1_epi16(32);
            let mut count = 0;
            for (perspective, accumulator) in [first, second].into_iter().enumerate() {
                let a = accumulator.as_ptr();
                for base in (0..L1 / 2).step_by(128) {
                    let mut vectors = [zero; 2];
                    for (pair, vector) in vectors.iter_mut().enumerate() {
                        let j = base + pair * 64;
                        let a0 = _mm512_loadu_si512(a.add(j).cast());
                        let a1 = _mm512_loadu_si512(a.add(j + 32).cast());
                        let b0 = _mm512_loadu_si512(a.add(L1 / 2 + j).cast());
                        let b1 = _mm512_loadu_si512(a.add(L1 / 2 + j + 32).cast());
                        let s0 = _mm512_slli_epi16::<7>(_mm512_max_epi16(
                            _mm512_min_epi16(a0, maximum),
                            zero,
                        ));
                        let s1 = _mm512_slli_epi16::<7>(_mm512_max_epi16(
                            _mm512_min_epi16(a1, maximum),
                            zero,
                        ));
                        let p0 = _mm512_mulhi_epi16(s0, _mm512_min_epi16(b0, maximum));
                        let p1 = _mm512_mulhi_epi16(s1, _mm512_min_epi16(b1, maximum));
                        *vector = _mm512_permutexvar_epi64(fix, _mm512_packus_epi16(p0, p1));
                        _mm512_storeu_si512(output.add(perspective * L1 / 2 + j).cast(), *vector);
                    }
                    let packed = _mm512_packs_epi32(vectors[0], vectors[1]);
                    let mask = _mm512_test_epi16_mask(packed, packed);
                    _mm512_storeu_si512(
                        indices.add(count).cast(),
                        _mm512_maskz_compress_epi16(mask, index),
                    );
                    count += mask.count_ones() as usize;
                    index = _mm512_add_epi16(index, step);
                }
            }
            count
        }
    }

    #[target_feature(enable = "avx512f,avx512bw,avx512vnni")]
    /// Indices of the non-zero 4-byte chunks of the fc_0 input, gathered with
    /// 16-bit compresses (two input vectors per step after a saturating pack,
    /// which keeps non-zero values non-zero). Writes up to 32 slack slots.
    #[target_feature(enable = "avx512f,avx512bw,avx512vbmi2")]
    unsafe fn nnz_vbmi2(inp: *const i32, nnz: *mut u16) -> usize {
        unsafe {
            // packs interleaves 4-element groups of the two inputs per 128-bit lane
            let mut idx = _mm512_set_epi16(
                31, 30, 29, 28, 15, 14, 13, 12, 27, 26, 25, 24, 11, 10, 9, 8, 23, 22, 21, 20, 7, 6,
                5, 4, 19, 18, 17, 16, 3, 2, 1, 0,
            );
            let step = _mm512_set1_epi16(32);
            let mut count = 0usize;
            for b in 0..FC0_CHUNKS / 32 {
                let v0 = _mm512_loadu_si512(inp.add(b * 32) as *const _);
                let v1 = _mm512_loadu_si512(inp.add(b * 32 + 16) as *const _);
                let packed = _mm512_packs_epi32(v0, v1);
                let m = _mm512_test_epi16_mask(packed, packed);
                _mm512_storeu_si512(
                    nnz.add(count) as *mut _,
                    _mm512_maskz_compress_epi16(m, idx),
                );
                count += m.count_ones() as usize;
                idx = _mm512_add_epi16(idx, step);
            }
            count
        }
    }

    #[target_feature(enable = "avx512f,avx512bw")]
    unsafe fn nnz_avx512(inp: *const i32, nnz: *mut u16) -> usize {
        unsafe {
            let mut count = 0usize;
            let mut idx = _mm512_setr_epi32(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15);
            let step = _mm512_set1_epi32(16);
            for b in 0..FC0_CHUNKS / 16 {
                let v = _mm512_loadu_si512(inp.add(b * 16) as *const _);
                let m = _mm512_test_epi32_mask(v, v);
                let c = _mm512_cvtepi32_epi16(_mm512_maskz_compress_epi32(m, idx));
                _mm256_storeu_si256(nnz.add(count) as *mut _, c);
                count += m.count_ones() as usize;
                idx = _mm512_add_epi32(idx, step);
            }
            count
        }
    }

    pub unsafe fn sparse_affine_fc0(input: &[u8; L1], w: &[i8], out: &mut [i32; L2]) {
        unsafe {
            let inp = input.as_ptr() as *const i32;
            // Non-zero chunk indices (32 slack slots for full-width stores).
            let mut nnz_buf = std::mem::MaybeUninit::<[u16; FC0_CHUNKS + 32]>::uninit();
            let nnz_ptr = nnz_buf.as_mut_ptr() as *mut u16;
            let count = if VBMI2.load(Relaxed) {
                nnz_vbmi2(inp, nnz_ptr)
            } else {
                nnz_avx512(inp, nnz_ptr)
            };
            sparse_affine_fc0_list(input, w, out, std::slice::from_raw_parts(nnz_ptr, count))
        }
    }

    #[target_feature(enable = "avx512f,avx512bw,avx512vnni")]
    pub(super) unsafe fn sparse_affine_fc0_list(
        input: &[u8; L1],
        w: &[i8],
        out: &mut [i32; L2],
        nnz: &[u16],
    ) {
        unsafe {
            let inp = input.as_ptr() as *const i32;
            let count = nnz.len();

            let mut a0 = _mm512_loadu_si512(out.as_ptr() as *const _);
            let mut a1 = _mm512_loadu_si512(out.as_ptr().add(16) as *const _);
            let (mut a2, mut a3, mut a4, mut a5) = (
                _mm512_setzero_si512(),
                _mm512_setzero_si512(),
                _mm512_setzero_si512(),
                _mm512_setzero_si512(),
            );
            let wp = w.as_ptr();
            let mut i = 0;
            while i + 2 < count {
                let c0 = *nnz.get_unchecked(i) as usize;
                let c1 = *nnz.get_unchecked(i + 1) as usize;
                let c2 = *nnz.get_unchecked(i + 2) as usize;
                let x0 = _mm512_set1_epi32(*inp.add(c0));
                let x1 = _mm512_set1_epi32(*inp.add(c1));
                let x2 = _mm512_set1_epi32(*inp.add(c2));
                let w0 = wp.add(c0 * 128);
                let w1 = wp.add(c1 * 128);
                let w2 = wp.add(c2 * 128);
                a0 = _mm512_dpbusd_epi32(a0, x0, _mm512_loadu_si512(w0 as *const _));
                a1 = _mm512_dpbusd_epi32(a1, x0, _mm512_loadu_si512(w0.add(64) as *const _));
                a2 = _mm512_dpbusd_epi32(a2, x1, _mm512_loadu_si512(w1 as *const _));
                a3 = _mm512_dpbusd_epi32(a3, x1, _mm512_loadu_si512(w1.add(64) as *const _));
                a4 = _mm512_dpbusd_epi32(a4, x2, _mm512_loadu_si512(w2 as *const _));
                a5 = _mm512_dpbusd_epi32(a5, x2, _mm512_loadu_si512(w2.add(64) as *const _));
                i += 3;
            }
            a0 = _mm512_add_epi32(_mm512_add_epi32(a0, a2), a4);
            a1 = _mm512_add_epi32(_mm512_add_epi32(a1, a3), a5);
            while i < count {
                let c0 = *nnz.get_unchecked(i) as usize;
                let x0 = _mm512_set1_epi32(*inp.add(c0));
                let w0 = wp.add(c0 * 128);
                a0 = _mm512_dpbusd_epi32(a0, x0, _mm512_loadu_si512(w0 as *const _));
                a1 = _mm512_dpbusd_epi32(a1, x0, _mm512_loadu_si512(w0.add(64) as *const _));
                i += 1;
            }
            _mm512_storeu_si512(out.as_mut_ptr() as *mut _, a0);
            _mm512_storeu_si512(out.as_mut_ptr().add(16) as *mut _, a1);
        }
    }

    #[target_feature(enable = "avx512f,avx512bw,avx512vnni")]
    pub unsafe fn dot128(input: &[u8; 128], w: &[i8; 128]) -> i32 {
        unsafe {
            let a = _mm512_dpbusd_epi32(
                _mm512_setzero_si512(),
                _mm512_loadu_si512(input.as_ptr() as *const _),
                _mm512_loadu_si512(w.as_ptr() as *const _),
            );
            let a = _mm512_dpbusd_epi32(
                a,
                _mm512_loadu_si512(input.as_ptr().add(64) as *const _),
                _mm512_loadu_si512(w.as_ptr().add(64) as *const _),
            );
            _mm512_reduce_add_epi32(a)
        }
    }

    #[target_feature(enable = "avx512f,avx512bw")]
    pub unsafe fn activations<const S: u32>(x: &[i32; 32], out: &mut [u8]) {
        unsafe {
            for h in 0..2 {
                let v = _mm512_loadu_si512(x.as_ptr().add(h * 16) as *const _);
                // Squared: exact 64-bit products of the even and odd lanes.
                let even = _mm512_mul_epi32(v, v);
                let odd = _mm512_mul_epi32(_mm512_srli_epi64::<32>(v), _mm512_srli_epi64::<32>(v));
                let sh = _mm_cvtsi32_si128((2 * S + 7) as i32);
                let lim = _mm512_set1_epi64(127);
                let e = _mm512_min_epi64(_mm512_srl_epi64(even, sh), lim);
                let o = _mm512_min_epi64(_mm512_srl_epi64(odd, sh), lim);
                // Interleave back: lane 2k = e[k], lane 2k + 1 = o[k]
                let sq = _mm512_or_si512(e, _mm512_slli_epi64::<32>(o));
                _mm_storeu_si128(
                    out.as_mut_ptr().add(h * 16) as *mut _,
                    _mm512_cvtepi32_epi8(sq),
                );
                // Linear clipped ReLU
                let lin = _mm512_min_epi32(
                    _mm512_max_epi32(
                        _mm512_sra_epi32(v, _mm_cvtsi32_si128(S as i32)),
                        _mm512_setzero_si512(),
                    ),
                    _mm512_set1_epi32(127),
                );
                _mm_storeu_si128(
                    out.as_mut_ptr().add(32 + h * 16) as *mut _,
                    _mm512_cvtepi32_epi8(lin),
                );
            }
        }
    }

    #[target_feature(enable = "avx512f,avx512bw,avx512vnni")]
    pub unsafe fn dense_affine_fc1(input: &[u8; 64], w: &[i8], out: &mut [i32; 32]) {
        unsafe {
            let inp = input.as_ptr() as *const i32;
            let mut acc0 = _mm512_loadu_si512(out.as_ptr() as *const _);
            let mut acc1 = _mm512_loadu_si512(out.as_ptr().add(16) as *const _);
            let wp = w.as_ptr();
            for c in 0..16 {
                let x = _mm512_set1_epi32(*inp.add(c));
                acc0 =
                    _mm512_dpbusd_epi32(acc0, x, _mm512_loadu_si512(wp.add(c * 128) as *const _));
                acc1 = _mm512_dpbusd_epi32(
                    acc1,
                    x,
                    _mm512_loadu_si512(wp.add(c * 128 + 64) as *const _),
                );
            }
            _mm512_storeu_si512(out.as_mut_ptr() as *mut _, acc0);
            _mm512_storeu_si512(out.as_mut_ptr().add(16) as *mut _, acc1);
        }
    }
    #[cfg(all(test, feature = "fused-input"))]
    mod fused_tests {
        use super::*;

        #[repr(align(64))]
        struct Input([u8; L1]);

        fn supported() -> bool {
            is_x86_feature_detected!("avx512f")
                && is_x86_feature_detected!("avx512bw")
                && is_x86_feature_detected!("avx512vnni")
                && is_x86_feature_detected!("avx512vbmi2")
        }

        fn next(state: &mut u64) -> u64 {
            *state ^= *state << 13;
            *state ^= *state >> 7;
            *state ^= *state << 17;
            *state
        }

        fn check(first: &[i16; L1], second: &[i16; L1], weights: &[i8]) {
            let mut actual = Input([0xa5; L1]);
            let mut indices = [std::mem::MaybeUninit::<u16>::uninit(); FC0_CHUNKS + 32];
            let count = unsafe {
                transform_sparse(
                    first,
                    second,
                    actual.0.as_mut_ptr(),
                    indices.as_mut_ptr().cast(),
                )
            };
            assert!(count <= FC0_CHUNKS);
            let indices =
                unsafe { std::slice::from_raw_parts(indices.as_ptr().cast::<u16>(), count) };
            let mut expected = Input([0; L1]);
            for (p, a) in [first, second].into_iter().enumerate() {
                for j in 0..L1 / 2 {
                    expected.0[p * L1 / 2 + j] = (i32::from(a[j].clamp(0, 255))
                        * i32::from(a[j + L1 / 2].clamp(0, 255))
                        / 512) as u8;
                }
            }
            assert_eq!(actual.0, expected.0);
            let mut previous = [0u16; FC0_CHUNKS + 32];
            let previous_count =
                unsafe { nnz_vbmi2(expected.0.as_ptr().cast(), previous.as_mut_ptr()) };
            assert_eq!(indices, &previous[..previous_count]);
            let mut sorted = indices.to_vec();
            sorted.sort_unstable();
            let membership: Vec<u16> = expected
                .0
                .chunks_exact(4)
                .enumerate()
                .filter_map(|(i, x)| x.iter().any(|&v| v != 0).then_some(i as u16))
                .collect();
            assert_eq!(sorted, membership);

            let biases: [i32; L2] = std::array::from_fn(|o| o as i32 * 37 - 900);
            let mut output = biases;
            unsafe {
                sparse_affine_fc0_list(&actual.0, weights, &mut output, indices);
            }
            let oracle: [i32; L2] = std::array::from_fn(|o| {
                let mut sum = i64::from(biases[o]);
                for c in 0..FC0_CHUNKS {
                    for k in 0..4 {
                        sum += i64::from(expected.0[c * 4 + k])
                            * i64::from(weights[c * L2 * 4 + o * 4 + k]);
                    }
                }
                i32::try_from(sum).unwrap()
            });
            assert_eq!(output, oracle);
        }

        #[test]
        fn fused_handle_keeps_aligned_initialized_input() {
            crate::nnue::init();
            let expected = level() == LEVEL_AVX512 && VBMI2.load(Relaxed);
            let input = FusedInput::new(&[255; L1], &[255; L1]);
            assert_eq!(input.is_some(), expected);
            if let Some(input) = input {
                assert_eq!(input.input.as_ptr() as usize % 64, 0);
                assert_eq!(input.len, FC0_CHUNKS);
                let weights = vec![1; L1 * L2];
                let mut output = [0; L2];
                input.affine(&weights, &mut output);
                assert_eq!(output, [127 * L1 as i32; L2]);
            }
        }

        #[test]
        fn fused_extremes_and_random_match_independent_oracles() {
            if !supported() {
                return;
            }
            let mut rng = 0x1a57_e2c3_d4b5_1901;
            let weights: Vec<i8> = (0..L1 * L2).map(|_| next(&mut rng) as i8).collect();
            for value in [i16::MIN, -1, 0, 1, 127, 254, 255, 256, i16::MAX] {
                check(&[value; L1], &[value; L1], &weights);
            }
            for _ in 0..128 {
                let first = std::array::from_fn(|_| next(&mut rng) as i16);
                let second = std::array::from_fn(|_| next(&mut rng) as i16);
                check(&first, &second, &weights);
            }
        }

        #[test]
        fn fused_every_single_input_byte_preserves_order_and_membership() {
            if !supported() {
                return;
            }
            let mut rng = 0xf051_17e5_2026_1019;
            let weights: Vec<i8> = (0..L1 * L2).map(|_| next(&mut rng) as i8).collect();
            for byte in 0..L1 {
                let mut a = [[0i16; L1]; 2];
                let p = byte / (L1 / 2);
                let j = byte % (L1 / 2);
                a[p][j] = 255;
                a[p][j + L1 / 2] = 255;
                check(&a[0], &a[1], &weights);
            }
        }
    }
}

#[cfg(target_arch = "x86_64")]
mod avx2 {
    use super::*;
    use std::arch::x86_64::*;

    const TILE: usize = 256; // i16 lanes per tile (16 ymm registers)
    const REGS: usize = TILE / 16;

    // Same register tiles as the row-slice kernel, without constructing heap
    // vectors of row references for every incremental update or cache refresh.
    #[target_feature(enable = "avx2")]
    pub unsafe fn update_acc_idx(dst: *mut i16, src: *const i16, r: &IdxRows) {
        unsafe {
            for t in 0..L1 / TILE {
                let base = t * TILE;
                let mut acc = [_mm256_setzero_si256(); REGS];
                for k in 0..REGS {
                    acc[k] = _mm256_loadu_si256(src.add(base + k * 16) as *const _);
                }
                for (weights, indices, subtract) in [
                    (r.base_psq, r.sub_psq, true),
                    (r.base_psq, r.add_psq, false),
                    (r.base8, r.sub8, true),
                    (r.base8, r.add8, false),
                ] {
                    for &index in indices {
                        let p = weights.add(index as usize * L1 + base);
                        for k in 0..REGS {
                            let w =
                                _mm256_cvtepi8_epi16(_mm_loadu_si128(p.add(k * 16) as *const _));
                            acc[k] = if subtract {
                                _mm256_sub_epi16(acc[k], w)
                            } else {
                                _mm256_add_epi16(acc[k], w)
                            };
                        }
                    }
                }
                for k in 0..REGS {
                    _mm256_storeu_si256(dst.add(base + k * 16) as *mut _, acc[k]);
                }
            }
        }
    }

    #[target_feature(enable = "avx2")]
    pub unsafe fn update_acc(dst: *mut i16, src: *const i16, rows: &Rows) {
        unsafe {
            for t in 0..L1 / TILE {
                let base = t * TILE;
                let mut acc = [_mm256_setzero_si256(); REGS];
                for k in 0..REGS {
                    acc[k] = _mm256_loadu_si256(src.add(base + k * 16) as *const _);
                }
                for r in rows.sub16 {
                    let p = r.as_ptr().add(base);
                    for k in 0..REGS {
                        acc[k] =
                            _mm256_sub_epi16(acc[k], _mm256_loadu_si256(p.add(k * 16) as *const _));
                    }
                }
                for r in rows.add16 {
                    let p = r.as_ptr().add(base);
                    for k in 0..REGS {
                        acc[k] =
                            _mm256_add_epi16(acc[k], _mm256_loadu_si256(p.add(k * 16) as *const _));
                    }
                }
                for r in rows.sub8 {
                    let p = r.as_ptr().add(base);
                    for k in 0..REGS {
                        let w = _mm256_cvtepi8_epi16(_mm_loadu_si128(p.add(k * 16) as *const _));
                        acc[k] = _mm256_sub_epi16(acc[k], w);
                    }
                }
                for r in rows.add8 {
                    let p = r.as_ptr().add(base);
                    for k in 0..REGS {
                        let w = _mm256_cvtepi8_epi16(_mm_loadu_si128(p.add(k * 16) as *const _));
                        acc[k] = _mm256_add_epi16(acc[k], w);
                    }
                }
                for k in 0..REGS {
                    _mm256_storeu_si256(dst.add(base + k * 16) as *mut _, acc[k]);
                }
            }
        }
    }

    #[target_feature(enable = "avx2")]
    pub unsafe fn transform_perspective(acc: &[i16; L1], out: &mut [u8]) {
        unsafe {
            let half = L1 / 2;
            let zero = _mm256_setzero_si256();
            let ftmax = _mm256_set1_epi16(255);
            let a = acc.as_ptr();
            for j in (0..half).step_by(32) {
                let a0 = _mm256_loadu_si256(a.add(j) as *const _);
                let a1 = _mm256_loadu_si256(a.add(j + 16) as *const _);
                let b0 = _mm256_loadu_si256(a.add(half + j) as *const _);
                let b1 = _mm256_loadu_si256(a.add(half + j + 16) as *const _);
                let s0 =
                    _mm256_slli_epi16::<7>(_mm256_max_epi16(_mm256_min_epi16(a0, ftmax), zero));
                let s1 =
                    _mm256_slli_epi16::<7>(_mm256_max_epi16(_mm256_min_epi16(a1, ftmax), zero));
                let p0 = _mm256_mulhi_epi16(s0, _mm256_min_epi16(b0, ftmax));
                let p1 = _mm256_mulhi_epi16(s1, _mm256_min_epi16(b1, ftmax));
                let packed = _mm256_permute4x64_epi64::<0b11_01_10_00>(_mm256_packus_epi16(p0, p1));
                _mm256_storeu_si256(out.as_mut_ptr().add(j) as *mut _, packed);
            }
        }
    }

    /// u8 x i8 dot products of 4-byte groups accumulated into i32 lanes
    /// (exact: inputs are at most 127, so the i16 pair sums cannot saturate).
    #[inline(always)]
    unsafe fn dpbusd(acc: __m256i, x: __m256i, w: __m256i) -> __m256i {
        unsafe {
            let p = _mm256_maddubs_epi16(x, w);
            _mm256_add_epi32(acc, _mm256_madd_epi16(p, _mm256_set1_epi16(1)))
        }
    }

    #[target_feature(enable = "avx2")]
    pub unsafe fn sparse_affine_fc0(input: &[u8; L1], w: &[i8], out: &mut [i32; L2]) {
        unsafe {
            let inp = input.as_ptr() as *const i32;
            let mut acc = [_mm256_setzero_si256(); 4];
            for k in 0..4 {
                acc[k] = _mm256_loadu_si256(out.as_ptr().add(k * 8) as *const _);
            }
            let wp = w.as_ptr();
            for b in 0..FC0_CHUNKS / 8 {
                let v = _mm256_loadu_si256(inp.add(b * 8) as *const _);
                let nz = _mm256_cmpeq_epi32(v, _mm256_setzero_si256());
                let mut m = (!_mm256_movemask_ps(_mm256_castsi256_ps(nz)) as u32) & 0xff;
                while m != 0 {
                    let c = b * 8 + m.trailing_zeros() as usize;
                    m &= m - 1;
                    let x = _mm256_set1_epi32(*inp.add(c));
                    let wc = wp.add(c * 128);
                    for k in 0..4 {
                        acc[k] = dpbusd(acc[k], x, _mm256_loadu_si256(wc.add(k * 32) as *const _));
                    }
                }
            }
            for k in 0..4 {
                _mm256_storeu_si256(out.as_mut_ptr().add(k * 8) as *mut _, acc[k]);
            }
        }
    }

    #[target_feature(enable = "avx2")]
    pub unsafe fn dense_affine_fc1(input: &[u8; 64], w: &[i8], out: &mut [i32; 32]) {
        unsafe {
            let inp = input.as_ptr() as *const i32;
            let mut acc = [_mm256_setzero_si256(); 4];
            for k in 0..4 {
                acc[k] = _mm256_loadu_si256(out.as_ptr().add(k * 8) as *const _);
            }
            let wp = w.as_ptr();
            for c in 0..16 {
                let x = _mm256_set1_epi32(*inp.add(c));
                for k in 0..4 {
                    acc[k] = dpbusd(
                        acc[k],
                        x,
                        _mm256_loadu_si256(wp.add(c * 128 + k * 32) as *const _),
                    );
                }
            }
            for k in 0..4 {
                _mm256_storeu_si256(out.as_mut_ptr().add(k * 8) as *mut _, acc[k]);
            }
        }
    }
}
