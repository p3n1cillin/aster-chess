// Aster core. Original attribution and source mapping: large_pages.rs.license.
// SPDX-License-Identifier: GPL-3.0-or-later
// Port of the upstream reference's Linux aligned_large_pages_alloc (memory.cpp):
// 2 MiB aligned anonymous memory advised as transparent huge pages.

/// Zero-initialized, 64-byte aligned (2 MiB aligned on Linux) memory.
///
/// On Linux the region is advised with `MADV_HUGEPAGE`, as the upstream reference does for
/// its network, histories and transposition table; on other systems (or if the
/// mapping fails) it falls back to an ordinary aligned heap allocation.
pub struct LargeMem {
    ptr: *mut u8,
    len: usize,
    _owner: Owner,
}

#[allow(dead_code)]
enum Owner {
    Map(memmap2::MmapMut),
    Heap(Vec<Line>),
}

#[repr(C, align(64))]
#[derive(Copy, Clone)]
struct Line([u8; 64]);

// The memory is uniquely owned; sharing follows the usual &/&mut rules.
unsafe impl Send for LargeMem {}
unsafe impl Sync for LargeMem {}

const HUGE: usize = 2 * 1024 * 1024;

impl LargeMem {
    pub fn zeroed(len: usize) -> Self {
        #[cfg(target_os = "linux")]
        if len >= HUGE {
            let size = len.div_ceil(HUGE) * HUGE;
            if let Ok(mut map) = memmap2::MmapOptions::new().len(size + HUGE).map_anon() {
                let base = map.as_mut_ptr();
                let offset = (base as usize).next_multiple_of(HUGE) - base as usize;
                let _ = map.advise_range(memmap2::Advice::HugePage, offset, size);
                return LargeMem {
                    ptr: unsafe { base.add(offset) },
                    len,
                    _owner: Owner::Map(map),
                };
            }
        }
        let mut lines = vec![Line([0; 64]); len.div_ceil(64).max(1)];
        LargeMem {
            ptr: lines.as_mut_ptr() as *mut u8,
            len,
            _owner: Owner::Heap(lines),
        }
    }

    #[inline(always)]
    pub fn as_ptr(&self) -> *const u8 {
        self.ptr
    }

    #[inline(always)]
    pub fn as_mut_ptr(&mut self) -> *mut u8 {
        self.ptr
    }

    #[inline(always)]
    pub fn len(&self) -> usize {
        self.len
    }

    #[inline(always)]
    pub fn is_empty(&self) -> bool {
        self.len == 0
    }
}

/// A fixed-length slice in [`LargeMem`]. Elements must not need dropping.
pub struct LargeSlice<T> {
    mem: LargeMem,
    len: usize,
    _t: std::marker::PhantomData<T>,
}

unsafe impl<T: Send> Send for LargeSlice<T> {}
unsafe impl<T: Sync> Sync for LargeSlice<T> {}

impl<T> LargeSlice<T> {
    fn alloc(len: usize) -> LargeMem {
        const { assert!(!std::mem::needs_drop::<T>() && std::mem::align_of::<T>() <= 64) };
        let bytes = len
            .checked_mul(std::mem::size_of::<T>())
            .expect("allocation size overflow");
        LargeMem::zeroed(bytes)
    }

    pub fn empty() -> Self {
        Self::from_fn(0, |_| unreachable!())
    }

    pub fn from_fn(len: usize, mut f: impl FnMut(usize) -> T) -> Self {
        let mut mem = Self::alloc(len);
        let p = mem.as_mut_ptr() as *mut T;
        for i in 0..len {
            unsafe { p.add(i).write(f(i)) };
        }
        LargeSlice {
            mem,
            len,
            _t: std::marker::PhantomData,
        }
    }

    /// # Safety
    /// The all-zero bit pattern must be a valid `T` (integers, atomics and arrays of them).
    pub unsafe fn zeroed(len: usize) -> Self {
        LargeSlice {
            mem: Self::alloc(len),
            len,
            _t: std::marker::PhantomData,
        }
    }
}

impl<T> std::ops::Deref for LargeSlice<T> {
    type Target = [T];
    #[inline(always)]
    fn deref(&self) -> &[T] {
        unsafe { std::slice::from_raw_parts(self.mem.as_ptr() as *const T, self.len) }
    }
}

impl<T> std::ops::DerefMut for LargeSlice<T> {
    #[inline(always)]
    fn deref_mut(&mut self) -> &mut [T] {
        unsafe { std::slice::from_raw_parts_mut(self.mem.as_mut_ptr() as *mut T, self.len) }
    }
}

/// A single value in [`LargeMem`]; the counterpart of `Box<T>` for large tables.
pub struct LargeBox<T>(LargeSlice<T>);

impl<T> LargeBox<T> {
    /// # Safety
    /// The all-zero bit pattern must be a valid `T`.
    pub unsafe fn zeroed() -> Self {
        LargeBox(unsafe { LargeSlice::zeroed(1) })
    }
}

impl<T> std::ops::Deref for LargeBox<T> {
    type Target = T;
    #[inline(always)]
    fn deref(&self) -> &T {
        unsafe { &*(self.0.mem.as_ptr() as *const T) }
    }
}

impl<T> std::ops::DerefMut for LargeBox<T> {
    #[inline(always)]
    fn deref_mut(&mut self) -> &mut T {
        unsafe { &mut *(self.0.mem.as_mut_ptr() as *mut T) }
    }
}
