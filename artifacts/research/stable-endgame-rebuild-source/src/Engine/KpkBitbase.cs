using System.Numerics;

namespace Aster;

// Original finite-state win attractor. The pawn is normalized to White and
// files a-d. Unresolved cycles after convergence are draws. No imported data.
public static class KpkBitbase
{
    private const int Entries = 24 * 64 * 64 * 2;
    private const byte Invalid = 0, Unknown = 1, Draw = 2, Win = 3;
    private sealed record Table(byte[] Results, ushort[] Distance, int Iterations);
    private static readonly Lazy<Table> Data = new(Build, LazyThreadSafetyMode.ExecutionAndPublication);
    public static void Initialize() => _ = Data.Value;
    private static int Index(int pawn, int ownKing, int bareKing, int side) =>
        (((pawn >> 3) - 1) * 4 + (pawn & 7)) * 8192 + ownKing * 128 + bareKing * 2 + side;

    private static bool Valid(int p, int k, int d, int side) => p != k && p != d && k != d
        && (Attacks.King[k] & (1UL << d)) == 0
        && (side != 0 || (Attacks.Pawn[0, p] & (1UL << d)) == 0);

    private static bool PromotionWins(int square, int ownKing, int defender, bool queen)
    {
        // A legal immediate capture of the new piece makes this promotion draw.
        if ((Attacks.King[defender] & (1UL << square)) != 0
            && (Attacks.King[ownKing] & (1UL << square)) == 0) return false;
        ulong PieceAttacks(int king)
        {
            ulong occupied = (1UL << square) | (1UL << ownKing) | (1UL << king);
            return Attacks.Rook(square, occupied) | (queen ? Attacks.Bishop(square, occupied) : 0);
        }
        bool check = (PieceAttacks(defender) & (1UL << defender)) != 0;
        ulong moves = Attacks.King[defender] & ~Attacks.King[ownKing] & ~(1UL << ownKing) & ~(1UL << square);
        while (moves != 0)
        {
            int destination = Attacks.Pop(ref moves);
            if ((PieceAttacks(destination) & (1UL << destination)) == 0) return true;
        }
        // With a surviving Q/R and legal kings, non-stalemate KQK/KRK is won.
        return check;
    }

    private static Table Build()
    {
        var result = new byte[Entries]; var distance = new ushort[Entries];
        for (int index = 0; index < Entries; index++)
        {
            int cell = index >> 13, p = (cell / 4 + 1) * 8 + cell % 4;
            int k = (index >> 7) & 63, d = (index >> 1) & 63, side = index & 1;
            if (Valid(p, k, d, side)) result[index] = Unknown;
        }
        int iterations = 0, changed;
        do
        {
            changed = 0; iterations++;
            for (int index = 0; index < Entries; index++)
            {
                if (result[index] != Unknown) continue;
                int cell = index >> 13, p = (cell / 4 + 1) * 8 + cell % 4;
                int k = (index >> 7) & 63, d = (index >> 1) & 63, side = index & 1;
                int moves = 0, best = side == 0 ? int.MaxValue : 0;
                bool won = side == 1;
                void Successor(int child)
                {
                    moves++;
                    bool win = result[child] == Win;
                    if (side == 0 && win) { won = true; best = Math.Min(best, distance[child] + 1); }
                    if (side == 1) { won &= win; if (win) best = Math.Max(best, distance[child] + 1); }
                }
                if (side == 0)
                {
                    ulong targets = Attacks.King[k] & ~Attacks.King[d] & ~(1UL << p) & ~(1UL << d);
                    while (targets != 0) Successor(Index(p, Attacks.Pop(ref targets), d, 1));
                    int to = p + 8;
                    if (to != k && to != d)
                    {
                        if ((p >> 3) == 6)
                        {
                            moves++;
                            if (PromotionWins(to, k, d, true) || PromotionWins(to, k, d, false)) { won = true; best = 1; }
                        }
                        else
                        {
                            Successor(Index(to, k, d, 1));
                            if ((p >> 3) == 1 && p + 16 != k && p + 16 != d) Successor(Index(p + 16, k, d, 1));
                        }
                    }
                }
                else
                {
                    ulong targets = Attacks.King[d] & ~Attacks.King[k] & ~(1UL << k) & ~Attacks.Pawn[0, p];
                    while (targets != 0)
                    {
                        int to = Attacks.Pop(ref targets);
                        if (to == p) { won = false; moves++; }
                        else Successor(Index(p, k, to, 0));
                    }
                    if (moves == 0)
                    {
                        won = (Attacks.Pawn[0, p] & (1UL << d)) != 0;
                        best = 0;
                    }
                }
                if (won && best != int.MaxValue)
                {
                    result[index] = Win; distance[index] = checked((ushort)best); changed++;
                }
            }
        } while (changed != 0);
        for (int i = 0; i < Entries; i++) if (result[i] == Unknown) result[i] = Draw;
        return new Table(result, distance, iterations);
    }

    public static bool Probe(Board board, out bool pawnWins, out int conversionBound)
    {
        pawnWins = false; conversionBound = 0;
        if (board.Castling != 0 || BitOperations.PopCount(board.Occupied) != 3
            || BitOperations.PopCount(board.Pieces[0] | board.Pieces[6]) != 1) return false;
        int color = board.Pieces[0] != 0 ? 0 : 1;
        int p = BitOperations.TrailingZeroCount(board.Pieces[color * 6]);
        int k = BitOperations.TrailingZeroCount(board.Pieces[color * 6 + 5]);
        int d = BitOperations.TrailingZeroCount(board.Pieces[(color ^ 1) * 6 + 5]);
        if (color == 1) { p ^= 56; k ^= 56; d ^= 56; }
        if ((p & 7) >= 4) { p ^= 7; k ^= 7; d ^= 7; }
        int side = board.Side == color ? 0 : 1;
        if ((p >> 3) is < 1 or > 6 || !Valid(p, k, d, side)) return false;
        int index = Index(p, k, d, side);
        var data = Data.Value;
        pawnWins = data.Results[index] == Win; conversionBound = data.Distance[index];
        return true;
    }

    public static bool TryEvaluate(Board board, out int score)
    {
        score = 0;
        if (!Probe(board, out bool won, out int bound)) return false;
        if (!won) return true;
        // This is a conservative bound to promotion or pawn checkmate, ignoring
        // intermediate clock resets. Decline uncertain rule-50 boundary probes.
        if (board.HalfmoveClock + bound >= 100) return false;
        int color = board.Pieces[0] != 0 ? 0 : 1;
        score = (board.Side == color ? 1 : -1) * (400 - bound);
        return true;
    }

    public static void Export(string path)
    {
        if (File.Exists(path)) throw new IOException("Preserve existing KPK exports.");
        var data = Data.Value;
        using var writer = new BinaryWriter(File.Create(path));
        writer.Write("ASTKPK01"u8); writer.Write(Entries); writer.Write(data.Results);
        foreach (ushort value in data.Distance) writer.Write(value);
    }
}
