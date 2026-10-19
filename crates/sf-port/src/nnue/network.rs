// Rust port of Stockfish 19 `nnue/network.*`, `nnue_architecture.h`,
// `nnue_feature_transformer.h` and the `layers/*` scalar semantics.
// Copyright (C) 2004-2026 The Stockfish developers (see AUTHORS file)
// Licensed under the GNU General Public License v3 or later.

use super::accumulator::{AccumulatorCaches, AccumulatorStack};
use super::features::*;
use super::aligned::AlignedBuf;
use super::kernels;
use crate::position::Position;
use crate::types::*;

pub const VERSION: u32 = 0x6A448AFA;
pub const L1: usize = 1024;
pub const L2: usize = 32;
pub const L3: usize = 32;
pub const PSQT_BUCKETS: usize = 8;
pub const LAYER_STACKS: usize = 8;
pub const OUTPUT_SCALE: i32 = 16;
pub const WEIGHT_SCALE_BITS: u32 = 6;
pub const HIDDEN_ONE_VAL: i64 = 128;

pub const THREAT_AND_PP_DIMENSIONS: usize = (THREAT_DIMENSIONS + PP_DIMENSIONS) as usize;

pub const DEFAULT_NET_NAME: &str = "nn-1a298aa575a0.nnue";

/// Input feature converter weights, stored in file (unpermuted) order:
/// one row of L1 values per input feature.
pub struct FeatureTransformer {
    pub biases: Box<[i16; L1]>,
    pub weights: AlignedBuf<i16>,                // PSQ_DIMENSIONS * L1
    pub threat_pp_weights: AlignedBuf<i8>,       // THREAT_AND_PP_DIMENSIONS * L1
    pub psqt_weights: AlignedBuf<i32>,           // PSQ_DIMENSIONS * PSQT_BUCKETS
    pub threat_pp_psqt_weights: AlignedBuf<i32>, // THREAT_AND_PP_DIMENSIONS * PSQT_BUCKETS
}

impl FeatureTransformer {
    pub fn hash_value() -> u32 {
        let mut h: u32 = 0;
        for c in [THREAT_HASH, PP_HASH, PSQ_HASH] {
            h = h.rotate_left(1);
            h ^= c;
        }
        h ^ (L1 as u32 * 2)
    }
}

/// One of the 8 layer stacks selected by piece count.
pub struct LayerStack {
    pub fc0_biases: [i32; L2],
    // Chunked layout (see kernels::chunk_layout): [L1 / 4][L2][4]
    pub fc0_weights: AlignedBuf<i8>,
    pub fc1_biases: [i32; L3],
    // Chunked layout: [64 / 4][L3][4]
    pub fc1_weights: AlignedBuf<i8>,
    pub fc2_bias: i32,
    pub fc2_weights: [i8; 128],
}

fn affine_hash(prev: u32, out_dims: u32) -> u32 {
    let mut h: u32 = 0xCC03DAE4u32.wrapping_add(out_dims);
    h ^= prev >> 1;
    h ^= prev << 31;
    h
}
fn relu_hash(prev: u32) -> u32 {
    0x538D24C7u32.wrapping_add(prev)
}

impl LayerStack {
    pub fn hash_value() -> u32 {
        let mut h: u32 = 0xEC42E90D;
        h ^= L1 as u32 * 2;
        h = affine_hash(h, L2 as u32);
        h = relu_hash(h);
        h = affine_hash(h, L3 as u32);
        h = relu_hash(h);
        h = affine_hash(h, 1);
        h
    }

    /// Forward propagation; returns the positional output in internal units * OutputScale.
    #[inline]
    pub fn propagate(&self, input: &[u8; L1]) -> i32 {
        let t = crate::prof::prof_start!();
        let mut fc0_out = self.fc0_biases;
        kernels::sparse_affine_fc0(input, &self.fc0_weights, &mut fc0_out);
        crate::prof::prof_end!(8, t);
        let t = crate::prof::prof_start!();

        let mut concat_a = Aligned([0u8; 128]);
        let concat = &mut concat_a.0;
        kernels::activations::<{ WEIGHT_SCALE_BITS + 1 }>(&fc0_out, &mut concat[..2 * L2]);

        let mut fc1_out = self.fc1_biases;
        kernels::dense_affine_fc1(concat[..64].try_into().unwrap(), &self.fc1_weights, &mut fc1_out);
        crate::prof::prof_end!(9, t);
        let t = crate::prof::prof_start!();
        kernels::activations::<WEIGHT_SCALE_BITS>(&fc1_out, &mut concat[2 * L2..]);

        let mut fwd = self.fc2_bias + kernels::dot128(concat, &self.fc2_weights);
        fwd += fc0_out[L2 - 2] - fc0_out[L2 - 1];

        crate::prof::prof_end!(10, t);
        let multiplier: i64 = 600 * OUTPUT_SCALE as i64;
        let denominator: i64 = HIDDEN_ONE_VAL * (1i64 << WEIGHT_SCALE_BITS) * 2;
        ((fwd as i64 * multiplier) / denominator) as i32
    }
}

pub struct Network {
    pub ft: FeatureTransformer,
    pub stacks: Vec<LayerStack>,
    pub description: String,
}

#[repr(C, align(64))]
struct Aligned<T>(T);

pub fn network_hash() -> u32 {
    FeatureTransformer::hash_value() ^ LayerStack::hash_value()
}

struct Reader<'a> {
    b: &'a [u8],
    i: usize,
}

impl<'a> Reader<'a> {
    fn take(&mut self, n: usize) -> Result<&'a [u8], String> {
        if self.i + n > self.b.len() {
            return Err("unexpected end of network file".into());
        }
        let s = &self.b[self.i..self.i + n];
        self.i += n;
        Ok(s)
    }
    fn u32(&mut self) -> Result<u32, String> {
        Ok(u32::from_le_bytes(self.take(4)?.try_into().unwrap()))
    }
    fn i32(&mut self) -> Result<i32, String> {
        Ok(i32::from_le_bytes(self.take(4)?.try_into().unwrap()))
    }
    fn i8s(&mut self, n: usize) -> Result<Vec<i8>, String> {
        Ok(self.take(n)?.iter().map(|&x| x as i8).collect())
    }
    /// Signed LEB128 block: magic string, byte count, then `count` values.
    fn leb128(&mut self, count: usize) -> Result<Vec<i32>, String> {
        const MAGIC: &[u8] = b"COMPRESSED_LEB128";
        if self.take(MAGIC.len())? != MAGIC {
            return Err("missing LEB128 magic".into());
        }
        let bytes = self.u32()? as usize;
        let data = self.take(bytes)?;
        let mut out = Vec::with_capacity(count);
        let mut p = 0;
        while out.len() < count {
            let mut result: u32 = 0;
            let mut shift: u32 = 0;
            loop {
                let Some(&byte) = data.get(p) else {
                    return Err("LEB128 data truncated".into());
                };
                p += 1;
                result |= ((byte & 0x7f) as u32) << (shift % 32);
                shift += 7;
                if byte & 0x80 == 0 {
                    let v = if shift >= 32 || byte & 0x40 == 0 { result } else { result | !((1u32 << shift) - 1) };
                    out.push(v as i32);
                    break;
                }
            }
        }
        if p != bytes {
            return Err("LEB128 byte count mismatch".into());
        }
        Ok(out)
    }
}

impl Network {
    pub fn load_bytes(bytes: &[u8]) -> Result<Network, String> {
        let mut r = Reader { b: bytes, i: 0 };
        let version = r.u32()?;
        let hash = r.u32()?;
        let size = r.u32()? as usize;
        if version != VERSION {
            return Err(format!("unsupported network version {version:#x}"));
        }
        let description = String::from_utf8_lossy(r.take(size)?).into_owned();
        if hash != network_hash() {
            return Err(format!("network hash {hash:#x} does not match architecture {:#x}", network_hash()));
        }

        if r.u32()? != FeatureTransformer::hash_value() {
            return Err("feature transformer hash mismatch".into());
        }
        let biases_v = r.leb128(L1)?;
        let mut biases = Box::new([0i16; L1]);
        for (b, v) in biases.iter_mut().zip(biases_v) {
            *b = v as i16;
        }
        let threat_w = r.i8s(THREAT_DIMENSIONS as usize * L1)?;
        let threat_psqt = r.leb128(THREAT_DIMENSIONS as usize * PSQT_BUCKETS)?;
        let pp_w = r.i8s(PP_DIMENSIONS as usize * L1)?;
        let pp_psqt = r.leb128(PP_DIMENSIONS as usize * PSQT_BUCKETS)?;
        let weights: Vec<i16> = r.leb128(PSQ_DIMENSIONS * L1)?.into_iter().map(|v| v as i16).collect();
        let psqt_weights = r.leb128(PSQ_DIMENSIONS * PSQT_BUCKETS)?;

        let mut threat_pp_weights = threat_w;
        threat_pp_weights.extend_from_slice(&pp_w);
        let mut threat_pp_psqt_weights = threat_psqt;
        threat_pp_psqt_weights.extend_from_slice(&pp_psqt);

        let ft = FeatureTransformer {
            biases,
            weights: AlignedBuf::from_slice(&weights),
            threat_pp_weights: AlignedBuf::from_slice(&threat_pp_weights),
            psqt_weights: AlignedBuf::from_slice(&psqt_weights),
            threat_pp_psqt_weights: AlignedBuf::from_slice(&threat_pp_psqt_weights),
        };
        super::features::set_prefetch_base(ft.threat_pp_weights.as_ptr());

        let mut stacks = Vec::with_capacity(LAYER_STACKS);
        for _ in 0..LAYER_STACKS {
            if r.u32()? != LayerStack::hash_value() {
                return Err("layer stack hash mismatch".into());
            }
            let mut fc0_biases = [0i32; L2];
            for b in fc0_biases.iter_mut() {
                *b = r.i32()?;
            }
            let fc0_weights = AlignedBuf::from_slice(&kernels::chunk_layout(&r.i8s(L2 * L1)?, L2, L1));
            let mut fc1_biases = [0i32; L3];
            for b in fc1_biases.iter_mut() {
                *b = r.i32()?;
            }
            let fc1_weights = AlignedBuf::from_slice(&kernels::chunk_layout(&r.i8s(L3 * 64)?, L3, 64));
            let fc2_bias = r.i32()?;
            let w2 = r.i8s(128)?;
            let mut fc2_weights = [0i8; 128];
            fc2_weights.copy_from_slice(&w2);
            stacks.push(LayerStack { fc0_biases, fc0_weights, fc1_biases, fc1_weights, fc2_bias, fc2_weights });
        }
        if r.i != bytes.len() {
            return Err("trailing data after network parameters".into());
        }
        Ok(Network { ft, stacks, description })
    }

    pub fn load_file(path: &std::path::Path) -> Result<Network, String> {
        let bytes = std::fs::read(path).map_err(|e| format!("{}: {e}", path.display()))?;
        Self::load_bytes(&bytes)
    }

    /// Returns (psqt, positional) in internal units.
    pub fn evaluate(&self, pos: &Position, stack: &mut AccumulatorStack, caches: &mut AccumulatorCaches) -> (Value, Value) {
        let t_total = crate::prof::prof_start!();
        let bucket = (popcount_all(pos) - 1) as usize / 4;
        let mut transformed = std::mem::MaybeUninit::<Aligned<[u8; L1]>>::uninit();

        let t = crate::prof::prof_start!();
        stack.evaluate(pos, &self.ft, caches);
        crate::prof::prof_end!(0, t);
        let t = crate::prof::prof_start!();
        let acc = stack.latest();
        let stm = pos.side_to_move();
        let psqt = (acc.psqt[stm][bucket] - acc.psqt[flip_color(stm)][bucket]) / 2;

        let persp = [stm, flip_color(stm)];
        // Fully written by the two transform calls below.
        let transformed = unsafe {
            let t = &mut (*transformed.as_mut_ptr()).0;
            for p in 0..2 {
                kernels::transform_perspective(&acc.accumulation[persp[p]], &mut t[p * L1 / 2..(p + 1) * L1 / 2]);
            }
            transformed.assume_init()
        };
        let transformed = &transformed.0;

        crate::prof::prof_end!(1, t);
        let t = crate::prof::prof_start!();
        let positional = self.stacks[bucket].propagate(transformed);
        crate::prof::prof_end!(2, t);
        crate::prof::prof_end!(5, t_total);
        (psqt / OUTPUT_SCALE, positional / OUTPUT_SCALE)
    }
}

#[inline(always)]
fn popcount_all(pos: &Position) -> i32 {
    pos.pieces().count_ones() as i32
}
