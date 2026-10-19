//! Strong standard-chess root checks for games and certificates, beyond permissive diagnostics.
use crate::chess::{
    board::{Board, Rules},
    fen::Fen,
    piece::{Colour, Piece, PieceType},
    types::{Rank, Square},
};

pub(crate) fn parse_standard(fen: &str) -> anyhow::Result<Board> {
    let parsed = Fen::parse(fen)?;
    anyhow::ensure!(
        parsed.fullmove.get() <= u32::MAX as usize,
        "Fullmove number exceeds the supported range"
    );
    for side in Colour::all() {
        anyhow::ensure!(parsed.board.colours[side].count() <= 16, "Too many pieces");
        anyhow::ensure!(
            (parsed.board.pieces[PieceType::Pawn] & parsed.board.colours[side]).count() <= 8,
            "Too many pawns"
        );
    }
    anyhow::ensure!(
        parsed.board.pieces[PieceType::Pawn].inner() & 0xff000000000000ff == 0,
        "Pawn on a back rank"
    );
    if let Some(ep) = parsed.ep {
        let white = parsed.turn == Colour::White;
        let behind = Square::new(if white { ep as u8 - 8 } else { ep as u8 + 8 }).unwrap();
        let origin = Square::new(if white { ep as u8 + 8 } else { ep as u8 - 8 }).unwrap();
        anyhow::ensure!(
            parsed.halfmove == 0
                && parsed.board.piece_at(ep).is_none()
                && parsed.board.piece_at(origin).is_none()
                && parsed.board.piece_at(behind) == Some(if white { Piece::BP } else { Piece::WP }),
            "Inconsistent en passant history"
        );
    }
    let board = Board::from_fen(fen)?;
    anyhow::ensure!(
        board.rules() == Rules::Classical,
        "The play/proof interface requires standard chess"
    );
    anyhow::ensure!(
        board.state.threats.checkers.count() <= 2,
        "Impossible triple check"
    );
    let canonical = board.to_string();
    let rights = canonical.split_whitespace().nth(2).unwrap();
    for (flag, king, rook, kp, rp) in [
        ('K', Square::E1, Square::H1, Piece::WK, Piece::WR),
        ('Q', Square::E1, Square::A1, Piece::WK, Piece::WR),
        ('k', Square::E8, Square::H8, Piece::BK, Piece::BR),
        ('q', Square::E8, Square::A8, Piece::BK, Piece::BR),
    ] {
        if rights.contains(flag) {
            anyhow::ensure!(
                parsed.board.piece_at(king) == Some(kp) && parsed.board.piece_at(rook) == Some(rp),
                "Inconsistent castling rights"
            );
        }
    }
    // The parsed EP rank has already been checked against the moving side.
    debug_assert!(
        parsed
            .ep
            .is_none_or(|sq| matches!(sq.rank(), Rank::Three | Rank::Six))
    );
    Ok(board)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn invalid_certificate_roots_rejected() {
        for fen in [
            "7k/5KP1/8/8/8/8/8/8 w - - 0 1",
            "4k3/8/8/8/8/8/8/4K3 w K - 0 1",
            "4r2k/8/8/8/1b6/5n2/8/4K3 w - - 0 1",
            "4k3/8/8/8/8/8/PPPPPPPP/P3K3 w - - 0 1",
            "4k3/8/8/8/8/8/8/4K3 w - e6 0 1",
        ] {
            assert!(parse_standard(fen).is_err(), "{fen}");
        }
        assert!(parse_standard("7k/6Q1/6K1/8/8/8/8/8 b - - 150 1").is_ok());
    }
}
