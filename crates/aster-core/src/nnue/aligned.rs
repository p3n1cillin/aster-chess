// 64-byte (cache line) aligned storage for network weights, so SIMD loads of
// weight rows never straddle cache lines. Large buffers are 2 MiB aligned and
// advised as transparent huge pages on Linux (see large_pages.rs).

use crate::large_pages::LargeMem;
use std::marker::PhantomData;

pub struct AlignedBuf<T: Copy> {
    mem: LargeMem,
    len: usize,
    _t: PhantomData<T>,
}

impl<T: Copy> AlignedBuf<T> {
    pub fn from_slice(v: &[T]) -> Self {
        let bytes = std::mem::size_of_val(v);
        let mut mem = LargeMem::zeroed(bytes);
        unsafe { std::ptr::copy_nonoverlapping(v.as_ptr() as *const u8, mem.as_mut_ptr(), bytes) };
        AlignedBuf {
            mem,
            len: v.len(),
            _t: PhantomData,
        }
    }
}

impl<T: Copy> std::ops::Deref for AlignedBuf<T> {
    type Target = [T];
    #[inline(always)]
    fn deref(&self) -> &[T] {
        unsafe { std::slice::from_raw_parts(self.mem.as_ptr() as *const T, self.len) }
    }
}
