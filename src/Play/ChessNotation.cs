using Aster;

namespace Aster.Play;

public static class ChessNotation
{
    public static string San(Board board, Move move)
    {
        Span<Move> legal = stackalloc Move[256]; int count = board.GenerateLegal(legal);
        if (!legal[..count].Contains(move)) throw new ArgumentException("Notation requires a legal move.");
        int piece = board.Squares[move.From], kind = piece % 6;
        string notation;
        if (move.IsCastle) notation = (move.To & 7) == 6 ? "O-O" : "O-O-O";
        else
        {
            notation = kind == 0 ? "" : "PNBRQK"[kind].ToString();
            if (kind != 0)
            {
                bool ambiguous = false, sameFile = false, sameRank = false;
                for (int i = 0; i < count; i++)
                {
                    Move other = legal[i];
                    if (other.From == move.From || other.To != move.To || board.Squares[other.From] != piece) continue;
                    ambiguous = true; sameFile |= (other.From & 7) == (move.From & 7); sameRank |= (other.From >> 3) == (move.From >> 3);
                }
                if (ambiguous) notation += !sameFile ? Move.SquareName(move.From)[..1] : !sameRank ? Move.SquareName(move.From)[1..] : Move.SquareName(move.From);
            }
            else if (move.IsCapture) notation = Move.SquareName(move.From)[..1];
            if (move.IsCapture) notation += "x";
            notation += Move.SquareName(move.To);
            if (move.Promotion != 0) notation += "=" + "PNBRQK"[move.Promotion];
        }
        if (!board.TryMakeMove(move)) throw new ArgumentException("Notation requires a legal move.");
        try { if (board.InCheck) notation += board.HasAnyLegalMove() ? "+" : "#"; }
        finally { board.UnmakeMove(); }
        return notation;
    }
    public static VariationMove[] Variation(Board root, IEnumerable<Move> pv)
    {
        Board board = root.Clone(); var result = new List<VariationMove>();
        foreach (Move move in pv)
        {
            string san = San(board, move);
            if (!board.TryMakeMove(move)) throw new InvalidOperationException("Illegal principal variation.");
            result.Add(new(move.ToString(), san, board.ToFen()));
        }
        return result.ToArray();
    }
}
