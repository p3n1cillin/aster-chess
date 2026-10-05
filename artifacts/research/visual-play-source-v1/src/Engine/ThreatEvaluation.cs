using System.Numerics;

namespace Aster;

// Original weights fit on training games only. Attacks are geometric, including
// pinned defenders; these features are not a static exchange calculation.
public static class ThreatEvaluation
{
    private static readonly int[] MgWeights = [12, 63, 34, 40, 38, 23, 28];
    private static readonly int[] EgWeights = [68, 35, 27, 23, 13, 21, 12];

    public static void ExtractFeatures(Board board, Span<int> features)
    {
        Span<ulong> control = stackalloc ulong[2], pawn = stackalloc ulong[2];
        Span<ulong> minor = stackalloc ulong[2], rook = stackalloc ulong[2];
        control.Clear(); pawn.Clear(); minor.Clear(); rook.Clear();
        for (int color = 0; color < 2; color++) for (int type = 0; type < 6; type++)
        {
            ulong pieces = board.Pieces[color * 6 + type];
            while (pieces != 0)
            {
                int square = Attacks.Pop(ref pieces);
                ulong attacks = type switch
                {
                    0 => Attacks.Pawn[color, square], 1 => Attacks.Knight[square],
                    2 => Attacks.Bishop(square, board.Occupied), 3 => Attacks.Rook(square, board.Occupied),
                    4 => Attacks.Bishop(square, board.Occupied) | Attacks.Rook(square, board.Occupied),
                    _ => Attacks.King[square]
                };
                control[color] |= attacks;
                if (type == 0) pawn[color] |= attacks;
                else if (type <= 2) minor[color] |= attacks;
                else if (type == 3) rook[color] |= attacks;
            }
        }
        FillFeatures(board, control, pawn, minor, rook, features);
    }

    public static void FillFeatures(Board board, ReadOnlySpan<ulong> control, ReadOnlySpan<ulong> pawn,
        ReadOnlySpan<ulong> minor, ReadOnlySpan<ulong> rook, Span<int> features)
    {
        if (features.Length < 7) throw new ArgumentException("Seven threat features required.");
        features[..7].Clear();
        for (int color = 0; color < 2; color++)
        {
            int opponent = color ^ 1, sign = color == 0 ? -1 : 1;
            for (int type = 0; type < 5; type++)
            {
                ulong pieces = board.Pieces[color * 6 + type];
                ulong loose = pieces & control[opponent] & ~control[color];
                int category = type == 0 ? 0 : type <= 2 ? 1 : type - 1;
                features[category] += sign * BitOperations.PopCount(loose);
                if (type == 0) continue;
                ulong lower = pawn[opponent];
                if (type >= 3) lower |= minor[opponent];
                if (type == 4) lower |= rook[opponent];
                category = type <= 2 ? 4 : type + 2;
                features[category] += sign * BitOperations.PopCount(pieces & lower & ~loose);
            }
        }
    }

    public static int WhiteCorrection(Board board, ReadOnlySpan<int> features)
    {
        int mg = 0, eg = 0;
        for (int i = 0; i < 7; i++) { mg += features[i] * MgWeights[i]; eg += features[i] * EgWeights[i]; }
        int phase = Math.Min(24, board.Phase);
        return (mg * phase + eg * (24 - phase)) / 24;
    }

    public static int WhiteCorrection(Board board, ReadOnlySpan<ulong> control, ReadOnlySpan<ulong> pawn,
        ReadOnlySpan<ulong> minor, ReadOnlySpan<ulong> rook)
    {
        Span<int> features = stackalloc int[7];
        FillFeatures(board, control, pawn, minor, rook, features);
        return WhiteCorrection(board, features);
    }
}
