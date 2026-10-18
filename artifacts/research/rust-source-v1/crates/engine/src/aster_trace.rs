//! Optional observations of genuine search positions; no search decisions are changed.
use crate::{chess::chessmove::Move, threadlocal::ThreadData};
use serde_json::{Value, json};
use std::{
    sync::{
        LazyLock, Mutex,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, Instant},
};
static ENABLED: AtomicBool = AtomicBool::new(false);
struct Trace {
    calls: u64,
    last: Instant,
    main: u64,
    q: u64,
    dest: [u64; 64],
    events: [u64; 4],
    roots: Vec<Value>,
    depth: i32,
}
impl Trace {
    fn new() -> Self {
        Self {
            calls: 0,
            last: Instant::now(),
            main: 0,
            q: 0,
            dest: [0; 64],
            events: [0; 4],
            roots: vec![],
            depth: 0,
        }
    }
}
static DATA: LazyLock<Mutex<Trace>> = LazyLock::new(|| Mutex::new(Trace::new()));
struct SharedTrace;
static SAMPLE: SharedTrace = SharedTrace;
impl SharedTrace {
    fn with_borrow_mut<R>(&self, f: impl FnOnce(&mut Trace) -> R) -> R {
        f(&mut DATA.lock().unwrap())
    }
    fn with_borrow<R>(&self, f: impl FnOnce(&Trace) -> R) -> R {
        f(&DATA.lock().unwrap())
    }
}

pub(crate) fn enable(value: bool) {
    ENABLED.store(value, Ordering::Relaxed);
    SAMPLE.with_borrow_mut(|s| *s = Trace::new());
}
fn enabled(t: &ThreadData<'_>) -> bool {
    ENABLED.load(Ordering::Relaxed) && t.thread_id == 0
}
pub(crate) fn event(t: &ThreadData<'_>, index: usize) {
    if enabled(t) {
        SAMPLE.with_borrow_mut(|s| s.events[index] += 1);
    }
}
pub(crate) fn root_begin(t: &ThreadData<'_>, m: Move) {
    if !enabled(t) {
        return;
    }
    SAMPLE.with_borrow_mut(|s|{
    if s.depth!=t.root_depth{s.depth=t.root_depth;s.roots.clear();}
    let name=m.display(t.board.rules()).to_string();s.roots.retain(|v|v["move"]!=name);
    s.roots.push(json!({"move":name,"score":null,"bound":"pending","nodes":-(t.info.nodes.get_local()as i64),"searching":true}));
});
}
pub(crate) fn root_end(t: &ThreadData<'_>, m: Move, score: i32, alpha: i32, beta: i32) {
    if !enabled(t) {
        return;
    }
    SAMPLE.with_borrow_mut(|s| {
        let name = m.display(t.board.rules()).to_string();
        if let Some(row) = s.roots.iter_mut().find(|v| v["move"] == name) {
            row["nodes"] =
                (t.info.nodes.get_local() as i64 + row["nodes"].as_i64().unwrap()).into();
            let formatted = crate::uci::fmt::format_score(score).to_string();
            let mut parts = formatted.split_whitespace();
            let kind = parts.next().unwrap();
            let value = parts.next().unwrap().parse::<i32>().unwrap();
            row["score"] = if kind == "mate" {
                value.signum() * (30000 - value.abs())
            } else {
                value
            }
            .into();
            row["bound"] = if score >= beta {
                "lower"
            } else if score <= alpha {
                "upper"
            } else {
                "exact"
            }
            .into();
            row["searching"] = false.into();
        }
    });
}
fn emit(t: &ThreadData<'_>, s: &Trace, finished: bool) {
    let line: Vec<_> =
        t.ss.iter()
            .take(t.board.height())
            .map(|f| {
                f.searching
                    .map_or_else(|| "null".into(), |m| m.display(t.board.rules()).to_string())
            })
            .collect();
    let roots: Vec<_> = s
        .roots
        .iter()
        .map(|v| {
            let mut row = v.clone();
            if row["searching"] == true {
                row["nodes"] = (t.info.nodes.get_local() as i64 + row["nodes"].as_i64().unwrap())
                    .max(0)
                    .into();
                if finished {
                    row["searching"] = false.into();
                    row["bound"] = "unfinished".into();
                }
            }
            row
        })
        .collect();
    println!(
        "info string aster-trace {}",
        json!({"fen":t.board.to_string(),"line":line,"depth":t.root_depth,"height":t.board.height(),
        "nodes":t.info.nodes.get_local(),"mainCalls":s.main,"qCalls":s.q,"destinationVisits":s.dest.to_vec(),
        "betaCutoffs":s.events[0],"tableCutoffs":s.events[1],"nullProbes":s.events[2],"reducedMoves":s.events[3],"rootMoves":roots,"finished":finished})
    );
}
pub(crate) fn observe(t: &ThreadData<'_>, quiescence: bool) {
    if !enabled(t) {
        return;
    }
    SAMPLE.with_borrow_mut(|s| {
        s.calls += 1;
        if quiescence {
            s.q += 1;
        } else {
            s.main += 1;
        }
        if t.board.height() > 0 {
            if let Some(m) = t.ss[t.board.height() - 1].searching {
                let dest = if m.is_castle() {
                    (m.from() as usize & !7) + if m.to() > m.from() { 6 } else { 2 }
                } else {
                    m.to() as usize
                };
                s.dest[dest] += 1;
            }
        }
        if s.calls % 512 == 0 && s.last.elapsed() >= Duration::from_millis(80) {
            s.last = Instant::now();
            emit(t, s, false);
        }
    });
}
pub(crate) fn finish(t: &ThreadData<'_>) {
    if enabled(t) {
        SAMPLE.with_borrow(|s| emit(t, s, true));
    }
}
