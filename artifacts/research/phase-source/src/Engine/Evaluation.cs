using System.Numerics;

namespace Aster;

// Original classical evaluation; all weights are provisional until match-tested.
public static class Evaluation
{
    public static readonly int[] Material = [100, 320, 335, 500, 950, 20000];
    public static readonly int[] PhaseWeight = [0, 1, 1, 2, 4, 0];
    public static readonly int[,] Mg = new int[12, 64], Eg = new int[12, 64];
    private static readonly ulong[] FileMask = new ulong[8];
    private static readonly ulong[,] PassedMask = new ulong[2, 64];
    private static readonly int[] PassedBonus = [0, 5, 10, 20, 38, 65, 110, 0];
    static Evaluation()
    {
        int[] mgValue = [100, 320, 335, 500, 950, 0], egValue = [120, 305, 325, 525, 930, 0];
        for (int file = 0; file < 8; file++) FileMask[file] = 0x0101010101010101UL << file;
        for (int color = 0; color < 2; color++) for (int square = 0; square < 64; square++)
        {
            int file = square & 7, rank = color == 0 ? square >> 3 : 7 - (square >> 3);
            int center = 7 - (Math.Abs(file * 2 - 7) + Math.Abs(rank * 2 - 7)) / 2;
            for (int type = 0; type < 6; type++)
            {
                int mg = type switch
                {
                    0 => rank * 7 + center * 3,
                    1 => center * 12 - (rank == 0 ? 15 : 0),
                    2 => center * 6 + rank * 3,
                    3 => rank * 2 + (rank == 6 ? 20 : 0),
                    4 => center * 3 - (rank > 2 ? 8 : 0),
                    _ => -center * 10 - rank * 8 + (rank == 0 && file is 1 or 2 or 6 ? 35 : 0)
                };
                int eg = type switch
                { 0 => rank * 12 + center * 2, 1 => center * 8, 2 => center * 5, 3 => rank * 3, 4 => center * 4, _ => center * 12 };
                int sign = color == 0 ? 1 : -1;
                Mg[color * 6 + type, square] = sign * (mgValue[type] + mg);
                Eg[color * 6 + type, square] = sign * (egValue[type] + eg);
            }
            for (int r = 0; r < 8; r++)
                if (color == 0 ? r > (square >> 3) : r < (square >> 3))
                    for (int f = Math.Max(0, file - 1); f <= Math.Min(7, file + 1); f++)
                        PassedMask[color, square] |= 1UL << (r * 8 + f);
        }
    }

    public static int Evaluate(Board board)
    {
#if ASTER_CONVERSION
        if (MajorMateBitbase.TryEvaluate(board, out int converted)) return converted;
#endif
#if ASTER_KPK || ASTER_CONVERSION
        if (KpkBitbase.TryEvaluate(board, out int exact)) return exact;
#endif
        if (board.Neural != null)
        {
            int white = board.Neural.WhiteScoreForSide(board.Side, board.Phase);
            if (board.Neural.Model.ClassicalBase) white = Math.Clamp(white, -250, 250);
            int baseline = board.Neural.Model.ClassicalBase ? EvaluateClassical(board) : 12;
            return Math.Clamp((board.Side == 0 ? white : -white) + baseline, -28000, 28000);
        }
        return EvaluateClassical(board);
    }
    public static int EvaluateClassical(Board board)
    {
        int mg = board.MgScore, eg = board.EgScore;
        ulong occupied = board.Occupied;
        int whiteKing = BitOperations.TrailingZeroCount(board.Pieces[5]);
        int blackKing = BitOperations.TrailingZeroCount(board.Pieces[11]);
        Span<ulong> pawnAttacks = stackalloc ulong[2];
        pawnAttacks[0] = PawnAttacks(board.Pieces[0], 0);
        pawnAttacks[1] = PawnAttacks(board.Pieces[6], 1);
        Span<ulong> control = stackalloc ulong[2];
        control[0] = pawnAttacks[0] | Attacks.King[whiteKing];
        control[1] = pawnAttacks[1] | Attacks.King[blackKing];
#if ASTER_THREATS
        Span<ulong> minorAttacks = stackalloc ulong[2], rookAttacks = stackalloc ulong[2];
        minorAttacks.Clear(); rookAttacks.Clear();
#endif
        for (int color = 0; color < 2; color++)
        {
            int sign = color == 0 ? 1 : -1, offset = color * 6;
            ulong pawns = board.Pieces[offset], enemyPawns = board.Pieces[(color ^ 1) * 6];
            if (BitOperations.PopCount(board.Pieces[offset + 2]) >= 2) { mg += sign * 28; eg += sign * 40; }
            for (int file = 0; file < 8; file++)
            {
                int n = BitOperations.PopCount(pawns & FileMask[file]);
                if (n > 1) { mg -= sign * 12 * (n - 1); eg -= sign * 18 * (n - 1); }
            }
            ulong remaining = pawns;
            while (remaining != 0)
            {
                int square = Attacks.Pop(ref remaining), file = square & 7;
                ulong adjacent = (file > 0 ? FileMask[file - 1] : 0) | (file < 7 ? FileMask[file + 1] : 0);
                if ((pawns & adjacent) == 0) { mg -= sign * 13; eg -= sign * 10; }
                if ((PassedMask[color, square] & enemyPawns) == 0)
                {
                    int rank = color == 0 ? square >> 3 : 7 - (square >> 3);
                    mg += sign * PassedBonus[rank]; eg += sign * PassedBonus[rank] * 2;
                }
                if ((Attacks.Pawn[color ^ 1, square] & pawns) != 0) { mg += sign * 7; eg += sign * 9; }
            }
            ulong enemyPawnAttacks = pawnAttacks[color ^ 1];
            for (int type = 1; type <= 4; type++)
            {
                remaining = board.Pieces[offset + type];
                while (remaining != 0)
                {
                    int square = Attacks.Pop(ref remaining);
                    ulong attacks = type switch
                    {
                        1 => Attacks.Knight[square], 2 => Attacks.Bishop(square, occupied),
                        3 => Attacks.Rook(square, occupied), _ => Attacks.Bishop(square, occupied) | Attacks.Rook(square, occupied)
                    };
                    control[color] |= attacks;
#if ASTER_THREATS
                    if (type <= 2) minorAttacks[color] |= attacks;
                    else if (type == 3) rookAttacks[color] |= attacks;
#endif
                    int mobility = BitOperations.PopCount(attacks & ~board.Colors[color] & ~enemyPawnAttacks);
                    mg += sign * mobility * (type <= 2 ? 4 : 2); eg += sign * mobility * 3;
                    if (type == 3 && (pawns & FileMask[square & 7]) == 0)
                    {
                        int bonus = (enemyPawns & FileMask[square & 7]) == 0 ? 22 : 12;
                        mg += sign * bonus; eg += sign * bonus;
                    }
                }
            }
            int king = color == 0 ? whiteKing : blackKing;
            ulong shelter = Attacks.Pawn[color, king] & pawns;
            mg += sign * BitOperations.PopCount(shelter) * 14;
        }
        int whiteDanger = BitOperations.PopCount(Attacks.King[whiteKing] & control[1]);
        int blackDanger = BitOperations.PopCount(Attacks.King[blackKing] & control[0]);
        mg += (blackDanger * blackDanger - whiteDanger * whiteDanger) * 3;
        int phase = Math.Min(24, board.Phase);
        int score = (mg * phase + eg * (24 - phase)) / 24;
#if ASTER_THREATS
        score += ThreatEvaluation.WhiteCorrection(board, control, pawnAttacks, minorAttacks, rookAttacks);
#endif
        return Math.Clamp((board.Side == 0 ? score : -score) + 12, -28000, 28000);
    }
    private static ulong PawnAttacks(ulong pawns, int color)
    {
        const ulong fileA = 0x0101010101010101UL, fileH = 0x8080808080808080UL;
        return color == 0
            ? ((pawns & ~fileA) << 7) | ((pawns & ~fileH) << 9)
            : ((pawns & ~fileH) >> 7) | ((pawns & ~fileA) >> 9);
    }
}
