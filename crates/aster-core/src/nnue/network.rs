// Aster core. Original attribution and source mapping: network.rs.license.
// SPDX-License-Identifier: GPL-3.0-or-later
// Modified 2026-10-19: source naming and notice layout; int8 network format without PSQT.

use super::accumulator::{AccumulatorCaches, AccumulatorStack};
use super::aligned::AlignedBuf;
use super::features::*;
use super::kernels;
use crate::position::Position;
use crate::types::*;

pub const VERSION: u32 = 0x6A448AFA;
pub const L1: usize = 1024;
pub const L2: usize = 32;
pub const L3: usize = 32;
pub const LAYER_STACKS: usize = 32;
pub const OUTPUT_SCALE: i32 = 16;
pub const WEIGHT_SCALE_BITS: u32 = 6;
pub const HIDDEN_ONE_VAL: i64 = 128;

pub const THREAT_AND_PP_DIMENSIONS: usize = (THREAT_DIMENSIONS + PP_DIMENSIONS) as usize;

pub const DEFAULT_NET_NAME: &str = "nn-c9e480e92425.nnue";

/// Input feature converter weights, stored in file (unpermuted) order:
/// one row of L1 values per input feature.
pub struct FeatureTransformer {
    pub biases: Box<[i16; L1]>,
    pub weights: AlignedBuf<i8>,           // PSQ_DIMENSIONS * L1
    pub threat_pp_weights: AlignedBuf<i8>, // THREAT_AND_PP_DIMENSIONS * L1
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

/// One of the 32 layer stacks, selected by piece count and queen presence.
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
        kernels::dense_affine_fc1(
            concat[..64].try_into().unwrap(),
            &self.fc1_weights,
            &mut fc1_out,
        );
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
    // Kept compile-gated alongside the existing path for the fixed experiment.
    #[cfg(feature = "fused-input")]
    #[inline]
    fn propagate_fused(&self, input: &kernels::FusedInput) -> i32 {
        let mut fc0_out = self.fc0_biases;
        input.affine(&self.fc0_weights, &mut fc0_out);
        let t = crate::prof::prof_start!();

        let mut concat_a = Aligned([0u8; 128]);
        let concat = &mut concat_a.0;
        kernels::activations::<{ WEIGHT_SCALE_BITS + 1 }>(&fc0_out, &mut concat[..2 * L2]);

        let mut fc1_out = self.fc1_biases;
        kernels::dense_affine_fc1(
            concat[..64].try_into().unwrap(),
            &self.fc1_weights,
            &mut fc1_out,
        );
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
    fn i8s(&mut self, n: usize) -> Result<&'a [i8], String> {
        let b = self.take(n)?;
        // i8 and u8 have identical size and alignment.
        Ok(unsafe { std::slice::from_raw_parts(b.as_ptr() as *const i8, n) })
    }
    fn i16s(&mut self, out: &mut [i16]) -> Result<(), String> {
        let bytes = self.take(out.len() * 2)?;
        for (o, b) in out.iter_mut().zip(bytes.chunks_exact(2)) {
            *o = i16::from_le_bytes([b[0], b[1]]);
        }
        Ok(())
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
            return Err(format!(
                "network hash {hash:#x} does not match architecture {:#x}",
                network_hash()
            ));
        }

        if r.u32()? != FeatureTransformer::hash_value() {
            return Err("feature transformer hash mismatch".into());
        }
        // Biases, threat rows, pawn-pair rows and piece-square rows, all
        // plain little-endian (int16 biases, int8 weights).
        let mut biases = Box::new([0i16; L1]);
        r.i16s(&mut biases[..])?;
        let threat_w = r.i8s(THREAT_DIMENSIONS as usize * L1)?;
        let pp_w = r.i8s(PP_DIMENSIONS as usize * L1)?;
        let weights = r.i8s(PSQ_DIMENSIONS * L1)?;

        let mut threat_pp_weights = Vec::with_capacity(threat_w.len() + pp_w.len());
        threat_pp_weights.extend_from_slice(threat_w);
        threat_pp_weights.extend_from_slice(pp_w);

        let ft = FeatureTransformer {
            biases,
            weights: AlignedBuf::from_slice(weights),
            threat_pp_weights: AlignedBuf::from_slice(&threat_pp_weights),
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
            let fc0_weights =
                AlignedBuf::from_slice(&kernels::chunk_layout(r.i8s(L2 * L1)?, L2, L1));
            let mut fc1_biases = [0i32; L3];
            for b in fc1_biases.iter_mut() {
                *b = r.i32()?;
            }
            let fc1_weights =
                AlignedBuf::from_slice(&kernels::chunk_layout(r.i8s(L3 * 64)?, L3, 64));
            let fc2_bias = r.i32()?;
            let mut fc2_weights = [0i8; 128];
            fc2_weights.copy_from_slice(r.i8s(128)?);
            stacks.push(LayerStack {
                fc0_biases,
                fc0_weights,
                fc1_biases,
                fc1_weights,
                fc2_bias,
                fc2_weights,
            });
        }
        if r.i != bytes.len() {
            return Err("trailing data after network parameters".into());
        }
        Ok(Network {
            ft,
            stacks,
            description,
        })
    }

    pub fn load_file(path: &std::path::Path) -> Result<Network, String> {
        let bytes = std::fs::read(path).map_err(|e| format!("{}: {e}", path.display()))?;
        Self::load_bytes(&bytes)
    }

    /// Raw network output in internal units, from the side to move's view.
    pub fn evaluate(
        &self,
        pos: &Position,
        stack: &mut AccumulatorStack,
        caches: &mut AccumulatorCaches,
    ) -> Value {
        let t_total = crate::prof::prof_start!();
        let bucket = Self::bucket(pos);
        let mut transformed = std::mem::MaybeUninit::<Aligned<[u8; L1]>>::uninit();

        let t = crate::prof::prof_start!();
        stack.evaluate(pos, &self.ft, caches);
        crate::prof::prof_end!(0, t);
        let t = crate::prof::prof_start!();
        let acc = stack.latest();
        let stm = pos.side_to_move();

        #[cfg(feature = "fused-input")]
        if let Some(input) =
            kernels::FusedInput::new(&acc.accumulation[stm], &acc.accumulation[flip_color(stm)])
        {
            crate::prof::prof_end!(1, t);
            let t = crate::prof::prof_start!();
            let positional = self.stacks[bucket].propagate_fused(&input);
            crate::prof::prof_end!(2, t);
            crate::prof::prof_end!(5, t_total);
            return positional / OUTPUT_SCALE;
        }

        let persp = [stm, flip_color(stm)];
        // Fully written by the two transform calls below.
        let transformed = unsafe {
            let t = &mut (*transformed.as_mut_ptr()).0;
            for p in 0..2 {
                kernels::transform_perspective(
                    &acc.accumulation[persp[p]],
                    &mut t[p * L1 / 2..(p + 1) * L1 / 2],
                );
            }
            transformed.assume_init()
        };
        let transformed = &transformed.0;

        crate::prof::prof_end!(1, t);
        let t = crate::prof::prof_start!();
        let positional = self.stacks[bucket].propagate(transformed);
        crate::prof::prof_end!(2, t);
        crate::prof::prof_end!(5, t_total);
        positional / OUTPUT_SCALE
    }

    /// Layer stack: four per piece-count band, by which sides have a queen.
    #[inline(always)]
    pub fn bucket(pos: &Position) -> usize {
        let stm = pos.side_to_move();
        let queens = ((pos.pieces_ct(stm, QUEEN) != 0) as usize) << 1
            | (pos.pieces_ct(flip_color(stm), QUEEN) != 0) as usize;
        (popcount_all(pos) - 1) as usize / 4 * 4 + queens
    }
}

#[inline(always)]
fn popcount_all(pos: &Position) -> i32 {
    pos.pieces().count_ones() as i32
}
