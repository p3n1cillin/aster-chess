// 64-byte (cache line) aligned storage for network weights, so SIMD loads of
// weight rows never straddle cache lines.

use std::marker::PhantomData;

#[repr(C, align(64))]
#[derive(Copy, Clone)]
struct Line([u8; 64]);

pub struct AlignedBuf<T: Copy> {
    lines: Vec<Line>,
    len: usize,
    _t: PhantomData<T>,
}

impl<T: Copy> AlignedBuf<T> {
    pub fn from_slice(v: &[T]) -> Self {
        let bytes = std::mem::size_of_val(v);
        let mut lines = vec![Line([0; 64]); bytes.div_ceil(64)];
        unsafe { std::ptr::copy_nonoverlapping(v.as_ptr() as *const u8, lines.as_mut_ptr() as *mut u8, bytes) };
        AlignedBuf { lines, len: v.len(), _t: PhantomData }
    }
}

impl<T: Copy> std::ops::Deref for AlignedBuf<T> {
    type Target = [T];
    #[inline(always)]
    fn deref(&self) -> &[T] {
        unsafe { std::slice::from_raw_parts(self.lines.as_ptr() as *const T, self.len) }
    }
}
