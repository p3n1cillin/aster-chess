//! Aster's bounded, complete mating strategies, ported from the original C# solver.
//! Cloned child boards keep speculative moves isolated even on limits or cancellation.
use crate::chess::{board::Board, piece::Colour};
use serde::Serialize;
use std::sync::atomic::{AtomicBool, Ordering};

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct Proof {
    schema: u8,
    pub complete: bool,
    reason: String,
    summary: String,
    root_fen: String,
    strong_side: u8,
    root_distance: u8,
    max_plies: u8,
    visits: usize,
    node_limit: usize,
    nodes: Vec<Node>,
}
#[derive(Serialize)]
struct Node {
    id: usize,
    fen: String,
    distance: u8,
    edges: Vec<Edge>,
}
#[derive(Serialize)]
struct Edge {
    r#move: String,
    to: usize,
}
struct Tree {
    fen: String,
    distance: u8,
    children: Vec<(String, Tree)>,
}

pub(crate) fn build(
    root: &Board,
    strong: Colour,
    bound: u8,
    limit: usize,
    cancel: &AtomicBool,
) -> Proof {
    let mut out = Proof { schema: 1, complete: false, reason: "unproven_within_bound".into(),
        summary: "No complete mating strategy proved within the bound; this does not establish a draw or loss.".into(),
        root_fen: root.to_string(), strong_side: strong as u8, root_distance: 0, max_plies: bound,
        visits: 0, node_limit: limit, nodes: vec![] };
    if bound > 7 || !(1..=100_000).contains(&limit) {
        out.reason = "invalid_limits".into();
        return out;
    }
    if crate::aster_rules::parse_standard(&root.to_string()).is_err() {
        out.reason = "invalid_position".into();
        out.summary =
            "The certificate root is not a valid supported standard-chess position.".into();
        return out;
    }
    fn visit(
        board: &Board,
        strong: Colour,
        remaining: u8,
        limit: usize,
        visits: &mut usize,
        cancel: &AtomicBool,
    ) -> Result<Option<Tree>, &'static str> {
        if cancel.load(Ordering::Relaxed) {
            return Err("cancelled");
        }
        if *visits == limit {
            return Err("node_limit");
        }
        *visits += 1;
        let mut moves = board.legal_moves();
        if moves.is_empty() {
            return Ok((board.in_check() && board.turn() != strong).then(|| Tree {
                fen: board.to_string(),
                distance: 0,
                children: vec![],
            }));
        }
        if remaining == 0
            || board.fifty_move_counter() >= 100
            || board.is_repetition()
            || board.is_insufficient_material()
        {
            return Ok(None);
        }
        let choose = board.turn() == strong;
        if choose {
            moves.sort_by_key(|m| std::cmp::Reverse(board.gives_check(*m)));
        }
        let mut children = vec![];
        let mut distance = 0;
        for m in moves {
            let mut child = board.clone();
            child.make_move_simple(m);
            match visit(&child, strong, remaining - 1, limit, visits, cancel)? {
                Some(mut tree) => {
                    // Certificates retain the FEN target after every double pawn push,
                    // including irrelevant targets omitted from the playing board's hash.
                    if board.state.mailbox[m.from()]
                        .is_some_and(|p| p.piece_type() == crate::chess::piece::PieceType::Pawn)
                        && m.is_double_pawn_push_ranks()
                    {
                        let text = m.display(board.rules()).to_string();
                        let mut fields: Vec<String> =
                            tree.fen.split_whitespace().map(str::to_string).collect();
                        fields[3] = format!(
                            "{}{}",
                            &text[..1],
                            if board.turn() == Colour::White {
                                "3"
                            } else {
                                "6"
                            }
                        );
                        tree.fen = fields.join(" ");
                    }
                    distance = distance.max(tree.distance + 1);
                    children.push((m.display(board.rules()).to_string(), tree));
                    if choose {
                        break;
                    }
                }
                None if !choose => return Ok(None),
                None => (),
            }
        }
        Ok((!children.is_empty()).then(|| Tree {
            fen: board.to_string(),
            distance,
            children,
        }))
    }
    fn flatten(tree: Tree, nodes: &mut Vec<Node>) -> usize {
        let id = nodes.len();
        nodes.push(Node {
            id,
            fen: tree.fen,
            distance: tree.distance,
            edges: vec![],
        });
        for (m, child) in tree.children {
            let to = flatten(child, nodes);
            nodes[id].edges.push(Edge { r#move: m, to });
        }
        id
    }
    let result = (|| {
        if let Some(tree) = visit(root, strong, 0, limit, &mut out.visits, cancel)? {
            return Ok(Some(tree));
        }
        if usize::from(root.fifty_move_counter()) + usize::from(bound) >= 100 {
            return Err("rule50_boundary");
        }
        // History-dependent roots require an explicit FEN origin or an irreversible reset.
        if !root.history().is_empty() && root.fifty_move_counter() != 0 {
            return Err("prior_history");
        }
        for depth in 1..=bound {
            if let Some(tree) = visit(root, strong, depth, limit, &mut out.visits, cancel)? {
                return Ok(Some(tree));
            }
        }
        Ok(None)
    })();
    match result {
        Ok(Some(tree)) => {
            out.complete = true;
            out.reason = "complete".into();
            out.root_distance = tree.distance;
            flatten(tree, &mut out.nodes);
            out.summary = format!(
                "{strong} forces checkmate within {} plies. Every legal defense is covered; all {} leaves/positions are replayable.",
                out.root_distance,
                out.nodes.len()
            );
        }
        Err(reason) => {
            out.reason = reason.into();
            out.summary = format!("No complete certificate exported: {reason}.");
        }
        Ok(None) => (),
    }
    out
}

pub(crate) fn cli(args: &[String]) -> anyhow::Result<()> {
    anyhow::ensure!(
        args.len() == 4,
        "Usage: aster certify-mate OUTPUT MAX_PLIES white|black \"FEN\""
    );
    let path = std::path::Path::new(&args[0]);
    anyhow::ensure!(!path.exists(), "Preserve existing certificates");
    let bound = args[1].parse()?;
    let strong = match args[2].as_str() {
        "white" => Colour::White,
        "black" => Colour::Black,
        _ => anyhow::bail!("Choose white or black"),
    };
    let board = crate::aster_rules::parse_standard(&args[3])?;
    let proof = build(&board, strong, bound, 100_000, &AtomicBool::new(false));
    if !proof.complete {
        println!("{}", serde_json::to_string(&proof)?);
        std::process::exit(2);
    }
    std::fs::write(path, serde_json::to_vec_pretty(&proof)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn mate_precedes_clock() {
        let b = Board::from_fen("7k/6Q1/6K1/8/8/8/8/8 b - - 150 1").unwrap();
        assert!(build(&b, Colour::White, 0, 1, &AtomicBool::new(false)).complete);
    }
    #[test]
    fn bounded_and_cancelled_restore_root() {
        let b = Board::startpos();
        let before = b.clone();
        assert!(!build(&b, Colour::White, 3, 1, &AtomicBool::new(false)).complete);
        assert_eq!(
            build(&b, Colour::White, 3, 100, &AtomicBool::new(true)).reason,
            "cancelled"
        );
        assert_eq!(b, before);
    }
    #[test]
    fn stalemate_is_not_proof() {
        let b = Board::from_fen("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1").unwrap();
        assert!(!build(&b, Colour::White, 3, 100, &AtomicBool::new(false)).complete);
    }
}
