using System.Numerics;

namespace Aster;

// A local swap-off calculation used for move ordering and conservative qsearch
// pruning. Pinned recapturers and unsafe king captures are excluded.
public static class StaticExchange
{
    public static int Evaluate(Board board, Move move)
    {
        if (move.IsCastle) return 0;
        Span<ulong> pieces = stackalloc ulong[12];
        board.Pieces.CopyTo(pieces);
        Span<int> gains = stackalloc int[32];
        int us = board.Side, from = move.From, to = move.To;
        int movingPiece = board.Squares[from];
        int capturedSquare = move.IsEnPassant ? to + (us == 0 ? -8 : 8) : to;
        int capturedPiece = board.Squares[capturedSquare];
        int placedPiece = move.Promotion == 0 ? movingPiece : us * 6 + move.Promotion;
        gains[0] = (capturedPiece < 0 ? 0 : Evaluation.Material[capturedPiece % 6])
            + (move.Promotion == 0 ? 0 : Evaluation.Material[move.Promotion] - Evaluation.Material[0]);
        pieces[movingPiece] &= ~(1UL << from);
        if (capturedPiece >= 0) pieces[capturedPiece] &= ~(1UL << capturedSquare);
        pieces[placedPiece] |= 1UL << to;
        ulong occupied = (board.Occupied & ~(1UL << from) & ~(1UL << capturedSquare)) | (1UL << to);
        int side = us ^ 1, depth = 0;
        // Pseudo-legal king captures can be unsafe; legality is checked by the
        // caller. Never simulate capturing a king in the swap-off sequence.
        while (depth < gains.Length - 1 && placedPiece % 6 != 5)
        {
            ulong attackers = Attackers(to, side, occupied, pieces);
            int selected = -1, selectedPiece = -1, promotedPiece = -1;
            ulong nextOccupied = occupied;
            for (int type = 0; type <= 5 && selected < 0; type++)
            {
                int piece = side * 6 + type;
                ulong candidates = attackers & pieces[piece];
                while (candidates != 0)
                {
                    int square = Attacks.Pop(ref candidates);
                    int promotion = type == 0 && (to >> 3) is 0 or 7 ? side * 6 + 4 : piece;
                    pieces[piece] &= ~(1UL << square);
                    pieces[placedPiece] &= ~(1UL << to);
                    pieces[promotion] |= 1UL << to;
                    nextOccupied = occupied & ~(1UL << square);
                    int king = BitOperations.TrailingZeroCount(pieces[side * 6 + 5]);
                    bool legal = Attackers(king, side ^ 1, nextOccupied, pieces) == 0;
                    if (legal) { selected = square; selectedPiece = piece; promotedPiece = promotion; break; }
                    pieces[promotion] &= ~(1UL << to);
                    pieces[placedPiece] |= 1UL << to;
                    pieces[piece] |= 1UL << square;
                }
            }
            if (selected < 0) break;
            depth++;
            gains[depth] = Evaluation.Material[placedPiece % 6] - gains[depth - 1]
                + (selectedPiece == promotedPiece ? 0 : Evaluation.Material[4] - Evaluation.Material[0]);
            placedPiece = promotedPiece; occupied = nextOccupied; side ^= 1;
        }
        for (int i = depth - 1; i >= 0; i--) gains[i] = -Math.Max(-gains[i], gains[i + 1]);
        return gains[0];
    }
    private static ulong Attackers(int square, int side, ulong occupied, ReadOnlySpan<ulong> pieces)
    {
        int offset = side * 6;
        return (Attacks.Pawn[side ^ 1, square] & pieces[offset])
            | (Attacks.Knight[square] & pieces[offset + 1])
            | (Attacks.Bishop(square, occupied) & (pieces[offset + 2] | pieces[offset + 4]))
            | (Attacks.Rook(square, occupied) & (pieces[offset + 3] | pieces[offset + 4]))
            | (Attacks.King[square] & pieces[offset + 5]);
    }
}
