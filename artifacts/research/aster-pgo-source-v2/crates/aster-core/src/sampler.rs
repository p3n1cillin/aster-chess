// Development-only sampling profiler for Windows x64 (enabled with
// `--features sampler`). A helper thread periodically suspends the target
// thread, records its instruction pointer and resumes it. Samples are written
// as module-relative addresses for offline symbolization with a linker map.

#![cfg(all(feature = "sampler", windows, target_arch = "x86_64"))]

use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, Ordering::Relaxed};

type Handle = *mut core::ffi::c_void;

#[repr(C, align(16))]
struct Context {
    data: [u8; 1232],
}

unsafe extern "system" {
    fn GetCurrentThreadId() -> u32;
    fn OpenThread(access: u32, inherit: i32, tid: u32) -> Handle;
    fn SuspendThread(h: Handle) -> u32;
    fn ResumeThread(h: Handle) -> u32;
    fn GetThreadContext(h: Handle, ctx: *mut Context) -> i32;
    fn GetModuleHandleW(name: *const u16) -> Handle;
    fn CloseHandle(h: Handle) -> i32;
    fn GetModuleHandleExW(flags: u32, addr: *const u16, out: *mut Handle) -> i32;
    fn GetModuleFileNameW(h: Handle, buf: *mut u16, n: u32) -> u32;
}

const THREAD_SUSPEND_RESUME: u32 = 0x0002;
const THREAD_GET_CONTEXT: u32 = 0x0008;
const THREAD_QUERY_INFORMATION: u32 = 0x0040;
const CONTEXT_CONTROL: u32 = 0x0010_0001;

static SAMPLES: Mutex<Vec<u32>> = Mutex::new(Vec::new());
static OUTSIDE: Mutex<Vec<u64>> = Mutex::new(Vec::new());
static CALLERS: Mutex<Vec<u32>> = Mutex::new(Vec::new());
static RUNNING: AtomicBool = AtomicBool::new(false);

/// Starts sampling the calling thread; call `stop` with the handle when done.
pub fn start() -> std::thread::JoinHandle<()> {
    let tid = unsafe { GetCurrentThreadId() };
    RUNNING.store(true, Relaxed);
    std::thread::spawn(move || unsafe {
        let h = OpenThread(
            THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION,
            0,
            tid,
        );
        let base = GetModuleHandleW(std::ptr::null()) as u64;
        let mut local = Vec::with_capacity(1 << 20);
        let mut outside = Vec::with_capacity(1 << 20);
        let mut callers = Vec::with_capacity(1 << 20);
        while RUNNING.load(Relaxed) {
            if SuspendThread(h) != u32::MAX {
                let mut ctx = Context { data: [0; 1232] };
                ctx.data[48..52].copy_from_slice(&CONTEXT_CONTROL.to_le_bytes());
                if GetThreadContext(h, &mut ctx) != 0 {
                    let rip = u64::from_le_bytes(ctx.data[248..256].try_into().unwrap());
                    let rva = rip.wrapping_sub(base);
                    if rva < 0x1000_0000 {
                        local.push(rva as u32);
                    } else {
                        outside.push(rip);
                        // Leaf functions (memcpy/memset): attribute to the caller at [rsp].
                        let rsp = u64::from_le_bytes(ctx.data[152..160].try_into().unwrap());
                        let ret = *(rsp as *const u64);
                        let rrva = ret.wrapping_sub(base);
                        if rrva < 0x1000_0000 {
                            callers.push(rrva as u32);
                        }
                    }
                }
                ResumeThread(h);
            }
            let t = std::time::Instant::now();
            while t.elapsed() < std::time::Duration::from_micros(50) {
                std::hint::spin_loop();
            }
        }
        CloseHandle(h);
        SAMPLES.lock().unwrap().extend(local);
        OUTSIDE.lock().unwrap().extend(outside);
        CALLERS.lock().unwrap().extend(callers);
    })
}

pub fn stop(handle: std::thread::JoinHandle<()>) {
    RUNNING.store(false, Relaxed);
    let _ = handle.join();
}

/// Writes all collected samples, one RVA per line.
pub fn write(path: &str) {
    let s = SAMPLES.lock().unwrap();
    let text: String = s.iter().map(|r| format!("{r:x}\n")).collect();
    let _ = std::fs::write(path, text);
    eprintln!("sampler: {} samples written to {path}", s.len());
    let o = OUTSIDE.lock().unwrap();
    let mut by_mod: std::collections::HashMap<String, usize> = std::collections::HashMap::new();
    for &rip in o.iter() {
        let mut h: Handle = std::ptr::null_mut();
        let name = unsafe {
            if GetModuleHandleExW(0x4 | 0x2, rip as *const u16, &mut h) != 0 {
                let mut buf = [0u16; 260];
                let n = GetModuleFileNameW(h, buf.as_mut_ptr(), 260);
                String::from_utf16_lossy(&buf[..n as usize])
            } else {
                "?".to_string()
            }
        };
        *by_mod.entry(name).or_default() += 1;
    }
    eprintln!("sampler: {} samples outside the executable", o.len());
    let c = CALLERS.lock().unwrap();
    let text: String = c
        .iter()
        .map(|r| {
            format!(
                "{r:x}
"
            )
        })
        .collect();
    let _ = std::fs::write("callers.txt", text);
    for (m, c) in by_mod {
        eprintln!("  {c:>8}  {m}");
    }
}
