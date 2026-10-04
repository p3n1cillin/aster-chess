using System.Numerics;

namespace Aster;

// Original breadth-first mate attractor for KQK/KRK, with reverse legal edges.
// No imported positions or data. Zero distance means invalid/draw unless marked won.
public static class MajorMateBitbase
{
    private const int Entries = 64 * 64 * 64 * 2;
    private sealed record Table(bool[] Won, byte[] Distance);
    private static readonly Lazy<Table> Rook = new(() => Build(false), LazyThreadSafetyMode.ExecutionAndPublication);
    private static readonly Lazy<Table> Queen = new(() => Build(true), LazyThreadSafetyMode.ExecutionAndPublication);
    public static void Initialize() { _ = Rook.Value; _ = Queen.Value; }
    private static int Index(int piece, int own, int bare, int side) => piece * 8192 + own * 128 + bare * 2 + side;
    private static ulong Rays(int piece, int own, int bare, bool queen) =>
        Attacks.Rook(piece, (1UL << piece) | (1UL << own) | (1UL << bare))
        | (queen ? Attacks.Bishop(piece, (1UL << piece) | (1UL << own) | (1UL << bare)) : 0);
    private static bool Valid(int p, int k, int d, int side, bool queen) => p != k && p != d && k != d
        && (Attacks.King[k] & (1UL << d)) == 0
        && (side != 0 || (Rays(p, k, d, queen) & (1UL << d)) == 0);

    private static Table Build(bool queen)
    {
        var won = new bool[Entries]; var distance = new byte[Entries];
        var pending = new byte[Entries]; var longest = new byte[Entries];
        var queue = new int[Entries]; int head = 0, tail = 0;
        for (int p = 0; p < 64; p++) for (int k = 0; k < 64; k++) for (int d = 0; d < 64; d++)
        {
            if (!Valid(p, k, d, 1, queen)) continue;
            int index = Index(p, k, d, 1), count = 0;
            ulong moves = Attacks.King[d] & ~Attacks.King[k] & ~(1UL << k);
            while (moves != 0)
            {
                int to = Attacks.Pop(ref moves);
                // A legal capture reaches bare kings, a drawing boundary. Count
                // it in pending, but it will never receive a winning notification.
                if (to == p || (Rays(p, k, to, queen) & (1UL << to)) == 0) count++;
            }
            pending[index] = (byte)count;
            if (count == 0 && (Rays(p, k, d, queen) & (1UL << d)) != 0)
            { won[index] = true; queue[tail++] = index; }
        }
        void Predecessor(int index, int childDistance, int side)
        {
            if (won[index]) return;
            if (side == 1)
            {
                longest[index] = (byte)Math.Max(longest[index], childDistance);
                if (--pending[index] != 0) return;
                childDistance = longest[index];
            }
            won[index] = true; distance[index] = checked((byte)(childDistance + 1)); queue[tail++] = index;
        }
        while (head < tail)
        {
            int index = queue[head++];
            int p = index >> 13, k = (index >> 7) & 63, d = (index >> 1) & 63, side = index & 1;
            if (side == 1)
            {
                ulong kings = Attacks.King[k];
                while (kings != 0)
                {
                    int from = Attacks.Pop(ref kings);
                    if (Valid(p, from, d, 0, queen)) Predecessor(Index(p, from, d, 0), distance[index], 0);
                }
                ulong pieces = Rays(p, k, d, queen) & ~(1UL << k) & ~(1UL << d);
                while (pieces != 0)
                {
                    int from = Attacks.Pop(ref pieces);
                    if (Valid(from, k, d, 0, queen)) Predecessor(Index(from, k, d, 0), distance[index], 0);
                }
            }
            else
            {
                ulong kings = Attacks.King[d];
                while (kings != 0)
                {
                    int from = Attacks.Pop(ref kings);
                    if (Valid(p, k, from, 1, queen)) Predecessor(Index(p, k, from, 1), distance[index], 1);
                }
            }
        }
        return new Table(won, distance);
    }

    public static bool Probe(Board board, out int strongSide, out bool won, out int mateDistance)
    {
        strongSide = 0; won = false; mateDistance = 0;
        if (board.Castling != 0 || BitOperations.PopCount(board.Occupied) != 3) return false;
        ulong majors = board.Pieces[3] | board.Pieces[4] | board.Pieces[9] | board.Pieces[10];
        if (BitOperations.PopCount(majors) != 1) return false;
        int p = BitOperations.TrailingZeroCount(majors);
        strongSide = (board.Colors[0] & majors) != 0 ? 0 : 1;
        int k = BitOperations.TrailingZeroCount(board.Pieces[strongSide * 6 + 5]);
        int d = BitOperations.TrailingZeroCount(board.Pieces[(strongSide ^ 1) * 6 + 5]);
        bool queen = (majors & (board.Pieces[4] | board.Pieces[10])) != 0;
        int side = board.Side == strongSide ? 0 : 1;
        if (!Valid(p, k, d, side, queen)) return false;
        var data = queen ? Queen.Value : Rook.Value; int index = Index(p, k, d, side);
        won = data.Won[index]; mateDistance = data.Distance[index]; return true;
    }

    public static bool TryEvaluate(Board board, out int score)
    {
        score = 0;
        if (!Probe(board, out int strong, out bool won, out int distance)) return false;
        if (!won) return true;
        if (board.HalfmoveClock + distance >= 100) return false;
        // Below mate-score encoding; search retains terminal/history precedence.
        score = (board.Side == strong ? 1 : -1) * (2000 - distance); return true;
    }

    public static bool TryRestrictRoot(Board board, ReadOnlySpan<Move> legal, Move[]? requested, out Move[] moves)
    {
        moves = [];
        if (!Probe(board, out int strong, out bool won, out int distance) || !won || strong != board.Side
            || distance == 0 || board.HalfmoveClock + distance >= 100 || board.IsRepetition()) return false;
        var progress = new List<Move>();
        foreach (Move move in legal)
        {
            if (requested != null && Array.IndexOf(requested, move) < 0) continue;
            if (!board.TryMakeMove(move)) continue;
            try
            {
                if (!board.HasPriorOccurrence() && Probe(board, out _, out bool childWon, out int childDistance)
                    && childWon && childDistance < distance) progress.Add(move);
            }
            finally { board.UnmakeMove(); }
        }
        if (progress.Count == 0) return false;
        moves = progress.ToArray(); return true;
    }

    public static void Export(string path, bool queen)
    {
        if (File.Exists(path)) throw new IOException("Preserve existing major-piece exports.");
        var data = queen ? Queen.Value : Rook.Value;
        using var writer = new BinaryWriter(File.Create(path));
        writer.Write("ASTMAJ01"u8); writer.Write(queen ? 4 : 3); writer.Write(Entries);
        for (int i = 0; i < Entries; i++)
        {
            int p = i >> 13, k = (i >> 7) & 63, d = (i >> 1) & 63;
            writer.Write((byte)(!Valid(p, k, d, i & 1, queen) ? 0 : data.Won[i] ? 3 : 2));
        }
        writer.Write(data.Distance);
    }
}
