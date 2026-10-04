using System.Numerics;
using System.Runtime.CompilerServices;

namespace Aster;

public static class Attacks
{
    public static readonly ulong[,] Pawn = new ulong[2, 64];
    public static readonly ulong[] Knight = new ulong[64], King = new ulong[64];
    private static readonly ulong[,] Rays = new ulong[8, 64];
    private static readonly (int File, int Rank)[] Directions =
        [(0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (-1, 1), (1, -1), (-1, -1)];

    static Attacks()
    {
        for (int square = 0; square < 64; square++)
        {
            int f = square & 7, r = square >> 3;
            foreach (var (df, dr) in new (int, int)[] { (1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2) })
                if (Inside(f + df, r + dr)) Knight[square] |= 1UL << (f + df + 8 * (r + dr));
            for (int dir = 0; dir < 8; dir++)
            {
                var (df, dr) = Directions[dir];
                if (Inside(f + df, r + dr)) King[square] |= 1UL << (f + df + 8 * (r + dr));
                for (int x = f + df, y = r + dr; Inside(x, y); x += df, y += dr)
                    Rays[dir, square] |= 1UL << (x + 8 * y);
            }
            for (int color = 0; color < 2; color++)
                foreach (int df in new[] { -1, 1 })
                    if (Inside(f + df, r + (color == 0 ? 1 : -1)))
                        Pawn[color, square] |= 1UL << (f + df + 8 * (r + (color == 0 ? 1 : -1)));
        }
    }
    private static bool Inside(int f, int r) => (uint)f < 8 && (uint)r < 8;
    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    private static ulong Ray(int dir, int square, ulong occupied)
    {
        ulong ray = Rays[dir, square], blockers = ray & occupied;
        if (blockers == 0) return ray;
        int nearest = dir is 0 or 2 or 4 or 5 ? BitOperations.TrailingZeroCount(blockers) : 63 - BitOperations.LeadingZeroCount(blockers);
        return ray ^ Rays[dir, nearest];
    }
    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    public static ulong Bishop(int square, ulong occupied) =>
        Ray(4, square, occupied) | Ray(5, square, occupied) | Ray(6, square, occupied) | Ray(7, square, occupied);
    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    public static ulong Rook(int square, ulong occupied) =>
        Ray(0, square, occupied) | Ray(1, square, occupied) | Ray(2, square, occupied) | Ray(3, square, occupied);
    [MethodImpl(MethodImplOptions.AggressiveInlining)]
    public static int Pop(ref ulong board)
    {
        int square = BitOperations.TrailingZeroCount(board);
        board &= board - 1;
        return square;
    }
}
