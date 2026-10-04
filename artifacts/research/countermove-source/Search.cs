using System.Diagnostics;
#if ASTER_PROFILE
using Eval = Aster.SearchProfile;
using See = Aster.SearchProfile;
#else
using Eval = Aster.Evaluation;
using See = Aster.StaticExchange;
#endif

namespace Aster;

public sealed record SearchLimits(int Depth = 64, long Nodes = long.MaxValue, long SoftMilliseconds = long.MaxValue,
    long HardMilliseconds = long.MaxValue, bool Infinite = false, Move[]? SearchMoves = null);
public sealed record SearchInfo(int Depth, int SelectiveDepth, int Score, long Nodes, long Milliseconds, int HashFull, Move[] Pv);
public sealed record SearchResult(Move BestMove, int Score, int Depth, long Nodes, long Milliseconds, Move[] Pv);

public sealed class Search(TranspositionTable table)
{
    public const int Mate = 30000, MateThreshold = 29000, MaxPly = 128;
    private const int Infinity = 32000;
    private readonly Move[] moveBuffer = new Move[MaxPly * 256];
    private readonly int[] scoreBuffer = new int[MaxPly * 256];
    private readonly Move[,] killers = new Move[MaxPly, 2];
    private readonly int[,,] history = new int[2, 64, 64];
    private readonly Move[,] counterMoves = new Move[12, 64];
    private readonly int[] previousPieces = new int[MaxPly];
    private readonly Move[] previousMoves = new Move[MaxPly];
    private readonly Move[,] pv = new Move[MaxPly, MaxPly];
    private readonly int[] pvLength = new int[MaxPly];
    private readonly Stopwatch clock = new();
    private Board board = null!;
    private SearchLimits limits = null!;
    private CancellationToken cancellation;
    private long nodes;
    private int selectiveDepth, rootPly;
    private sealed class SearchStoppedException : Exception;

    public SearchResult Run(Board position, SearchLimits searchLimits, CancellationToken token = default, Action<SearchInfo>? report = null)
    {
        board = position; limits = searchLimits; cancellation = token;
        nodes = 0; selectiveDepth = 0; rootPly = board.Ply;
#if ASTER_PROFILE
        SearchProfile.Reset();
#endif
        clock.Restart(); table.NewSearch();
        Array.Clear(killers); Array.Clear(pvLength);
        Array.Clear(counterMoves); Array.Fill(previousPieces, -1);
        for (int side = 0; side < 2; side++) for (int from = 0; from < 64; from++) for (int to = 0; to < 64; to++)
            history[side, from, to] /= 2;
        Span<Move> legal = stackalloc Move[256];
        int count = board.GenerateLegal(legal);
        Move fallback = Move.None;
        for (int i = 0; i < count; i++)
            if (limits.SearchMoves == null || Array.IndexOf(limits.SearchMoves, legal[i]) >= 0) { fallback = legal[i]; break; }
        if (fallback == Move.None)
            return new SearchResult(Move.None, count == 0 && board.InCheck ? -Mate : 0, 0, 0, clock.ElapsedMilliseconds, []);
        Move bestMove = fallback;
        int bestScore = 0, completedDepth = 0;
        Move[] bestPv = [fallback];
        for (int depth = 1; depth <= Math.Clamp(limits.Depth, 1, MaxPly - 2); depth++)
        {
            try
            {
                CheckStopped(forceTime: true);
                int window = 35, alpha = depth >= 4 ? Math.Max(-Infinity, bestScore - window) : -Infinity;
                int beta = depth >= 4 ? Math.Min(Infinity, bestScore + window) : Infinity;
                int score;
                while (true)
                {
                    score = Negamax(depth, 0, alpha, beta, true);
                    if (score <= alpha && alpha > -Infinity) alpha = Math.Max(-Infinity, alpha - window);
                    else if (score >= beta && beta < Infinity) beta = Math.Min(Infinity, beta + window);
                    else break;
                    window = Math.Min(Infinity, window * 2);
                }
                if (pvLength[0] > 0)
                {
                    bestPv = new Move[pvLength[0]];
                    for (int i = 0; i < bestPv.Length; i++) bestPv[i] = pv[0, i];
                    bestMove = bestPv[0];
                }
                bestScore = score; completedDepth = depth;
                report?.Invoke(new SearchInfo(depth, selectiveDepth, score, nodes, clock.ElapsedMilliseconds, table.HashFull, bestPv));
                if (!limits.Infinite && clock.ElapsedMilliseconds >= limits.SoftMilliseconds) break;
                if (!limits.Infinite && Math.Abs(score) > MateThreshold && Mate - Math.Abs(score) <= depth) break;
            }
            catch (SearchStoppedException) { break; }
        }
        return new SearchResult(bestMove, bestScore, completedDepth, nodes, clock.ElapsedMilliseconds, bestPv);
    }

    private void Visit(int ply)
    {
        CheckStopped(); nodes++;
        selectiveDepth = Math.Max(selectiveDepth, ply);
        pvLength[ply] = ply;
    }
    private void CheckStopped(bool forceTime = false)
    {
        if (cancellation.IsCancellationRequested || nodes >= limits.Nodes
            || (!limits.Infinite && (forceTime || (nodes & 255) == 0) && clock.ElapsedMilliseconds >= limits.HardMilliseconds))
            throw new SearchStoppedException();
    }
    private bool IsDraw() => board.IsRepetition(rootPly) || board.InsufficientMaterial() || board.HalfmoveClock >= 100;
    private bool HasAnyLegalMove()
    {
#if ASTER_PROFILE
        long started = Stopwatch.GetTimestamp();
        try
        {
#endif
        return board.HasAnyLegalMove();
#if ASTER_PROFILE
        }
        finally { SearchProfile.RecordLegal(started); }
#endif
    }
    private int DrawOrMate(int ply) => board.InCheck && !HasAnyLegalMove() ? -Mate + ply : 0;

    private int Negamax(int depth, int ply, int alpha, int beta, bool allowNull)
    {
        if (depth <= 0) return Quiescence(ply, alpha, beta);
        Visit(ply);
        if (IsDraw()) return DrawOrMate(ply);
        if (ply >= MaxPly - 1) return !HasAnyLegalMove() ? (board.InCheck ? -Mate + ply : 0) : Eval.Evaluate(board);
        bool inCheck = board.InCheck;
        if (inCheck) depth++;
        alpha = Math.Max(alpha, -Mate + ply); beta = Math.Min(beta, Mate - ply - 1);
        if (alpha >= beta) return alpha;
        int originalAlpha = alpha;
        bool isPv = beta - alpha > 1;
        bool repeated = board.HasPriorOccurrence();
        ulong key = board.SearchKey;
        Move ttMove = Move.None;
        if (table.Probe(key, ply, out ttMove, out int ttScore, out int ttDepth, out Bound ttBound)
            && ply > 0 && !isPv && !repeated && ttDepth >= depth
            && (ttBound == Bound.Exact || (ttBound == Bound.Lower && ttScore >= beta) || (ttBound == Bound.Upper && ttScore <= alpha)))
            return ttScore;
        int staticEval = inCheck ? -Infinity : Eval.Evaluate(board);
        bool hasNonPawnMaterial = (board.Colors[board.Side] & ~(board.Pieces[board.Side * 6] | board.Pieces[board.Side * 6 + 5])) != 0;
        // Shallow reverse futility is restricted to non-PV, non-check nodes
        // with non-pawn material. Establish a legal move before pruning so a
        // stalemate can never be assigned a stand-pat value.
        if (ply > 0 && !isPv && !inCheck && !repeated && hasNonPawnMaterial && depth <= 6
            && board.HalfmoveClock < 90 && Math.Abs(beta) < MateThreshold && staticEval - 85 * depth >= beta)
            return HasAnyLegalMove() ? staticEval : 0;
        // Guard null move against pawn-only zugzwang and the rule-50 boundary.
        if (ply > 0 && !isPv && !inCheck && allowNull && depth >= 3 && staticEval >= beta
            && board.HalfmoveClock < 90 && hasNonPawnMaterial)
        {
            if (!HasAnyLegalMove()) return 0;
            int score;
            previousPieces[ply] = -1;
            board.MakeNullMove();
            try { score = -Negamax(depth - 1 - (2 + depth / 4), ply + 1, -beta, -beta + 1, false); }
            finally { board.UnmakeMove(); }
            if (score >= beta && score < MateThreshold) return score;
        }

        var moves = moveBuffer.AsSpan(ply * 256, 256);
        var scores = scoreBuffer.AsSpan(ply * 256, 256);
        int count = board.GeneratePseudoLegal(moves);
        ScoreMoves(moves, scores, count, ttMove, ply);
        int bestScore = -Infinity, legalCount = 0;
        Move best = Move.None;
        int us = board.Side;
        for (int i = 0; i < count; i++)
        {
            SelectNext(moves, scores, i, count);
            Move move = moves[i];
            if (ply == 0 && limits.SearchMoves != null && Array.IndexOf(limits.SearchMoves, move) < 0) continue;
            int movingPiece = board.Squares[move.From];
            if (!board.TryMakeMove(move)) continue;
            previousPieces[ply] = movingPiece; previousMoves[ply] = move;
            legalCount++;
            int score;
            try
            {
                bool givesCheck = board.InCheck;
                if (legalCount == 1) score = -Negamax(depth - 1, ply + 1, -beta, -alpha, true);
                else
                {
                    int reduction = depth >= 3 && legalCount >= 4 && move.IsQuiet && !inCheck && !givesCheck
                        ? Math.Min(depth - 2, 1 + (int)(Math.Log(depth) * Math.Log(legalCount) / 2.5) - (isPv ? 1 : 0)) : 0;
#if ASTER_PROFILE
                    SearchProfile.RecordReduction(reduction);
#endif
                    score = -Negamax(depth - 1 - reduction, ply + 1, -alpha - 1, -alpha, true);
                    if (reduction > 0 && score > alpha) score = -Negamax(depth - 1, ply + 1, -alpha - 1, -alpha, true);
                    if (score > alpha && score < beta) score = -Negamax(depth - 1, ply + 1, -beta, -alpha, true);
                }
            }
            finally { board.UnmakeMove(); }
            if (score > bestScore) { bestScore = score; best = move; }
            if (score > alpha)
            {
                alpha = score; UpdatePv(ply, move);
                if (alpha >= beta)
                {
                    if (move.IsQuiet)
                    {
                        if (killers[ply, 0] != move) { killers[ply, 1] = killers[ply, 0]; killers[ply, 0] = move; }
                        if (ply > 0 && previousPieces[ply - 1] >= 0)
                            counterMoves[previousPieces[ply - 1], previousMoves[ply - 1].To] = move;
                        int bonus = Math.Min(1600, depth * depth * 24);
                        ref int h = ref history[us, move.From, move.To];
                        h += bonus - h * bonus / 16384;
                    }
                    break;
                }
            }
        }
        if (legalCount == 0) return inCheck ? -Mate + ply : 0;
        Bound bound = bestScore >= beta ? Bound.Lower : bestScore > originalAlpha ? Bound.Exact : Bound.Upper;
        if (!repeated && !(ply == 0 && limits.SearchMoves != null)) table.Store(key, best, bestScore, depth, bound, ply);
        return bestScore;
    }

    private int Quiescence(int ply, int alpha, int beta)
    {
        Visit(ply);
        if (IsDraw()) return DrawOrMate(ply);
        bool inCheck = board.InCheck;
        int originalAlpha = alpha;
        // Non-check qsearch continuations are captures/promotions, which reset
        // reversible history. Keep check-evasion nodes uncached and never use
        // a deeper, potentially history-dependent main-search entry here.
        bool cacheable = !inCheck && !board.HasPriorOccurrence();
        ulong key = board.SearchKey;
        Move ttMove = Move.None;
        int ttScore = 0, ttDepth = -1;
        Bound ttBound = Bound.None;
        bool knownLegal = cacheable && table.Probe(key, ply, out ttMove, out ttScore, out ttDepth, out ttBound) && ttDepth == 0;
        // Only qsearch creates depth-zero entries, after proving a legal move
        // exists. Reuse that structural fact with the full position key. Deeper
        // entries do not carry this guarantee; draw history is checked above.
        if (!knownLegal && !HasAnyLegalMove()) return inCheck ? -Mate + ply : 0;
        if (ply >= MaxPly - 1) return Eval.Evaluate(board);
        if (knownLegal && beta - alpha == 1
            && (ttBound == Bound.Exact || (ttBound == Bound.Lower && ttScore >= beta) || (ttBound == Bound.Upper && ttScore <= alpha)))
            return ttScore;
        int best = inCheck ? -Infinity : Eval.Evaluate(board);
        Move bestMove = Move.None;
        if (!inCheck)
        {
            if (best >= beta)
            {
                if (cacheable) table.Store(key, Move.None, best, 0, Bound.Lower, ply);
                return best;
            }
            alpha = Math.Max(alpha, best);
        }
        var moves = moveBuffer.AsSpan(ply * 256, 256);
        var scores = scoreBuffer.AsSpan(ply * 256, 256);
        int count = board.GeneratePseudoLegal(moves, !inCheck);
        ScoreMoves(moves, scores, count, ttMove, ply);
        for (int i = 0; i < count; i++)
        {
            SelectNext(moves, scores, i, count);
            Move move = moves[i];
            // Keep promotions, checks, and all evasions regardless of SEE.
            bool losingCapture = !inCheck && move.IsCapture && move.Promotion == 0
                && (move == ttMove ? See.Evaluate(board, move) < 0 : scores[i] < 500_000);
            int movingPiece = board.Squares[move.From];
            if (!board.TryMakeMove(move)) continue;
            previousPieces[ply] = movingPiece; previousMoves[ply] = move;
            if (losingCapture && !board.InCheck) { board.UnmakeMove(); continue; }
            int score;
            try { score = -Quiescence(ply + 1, -beta, -alpha); }
            finally { board.UnmakeMove(); }
            if (score > best) { best = score; bestMove = move; }
            if (score > alpha)
            {
                alpha = score; UpdatePv(ply, move);
                if (alpha >= beta)
                {
                    if (cacheable) table.Store(key, move, score, 0, Bound.Lower, ply);
                    return score;
                }
            }
        }
        if (cacheable) table.Store(key, bestMove, best, 0, best > originalAlpha ? Bound.Exact : Bound.Upper, ply);
        return best;
    }
    private void UpdatePv(int ply, Move move)
    {
        pv[ply, ply] = move;
        int length = pvLength[ply + 1];
        for (int i = ply + 1; i < length; i++) pv[ply, i] = pv[ply + 1, i];
        pvLength[ply] = Math.Max(ply + 1, length);
    }
    private void ScoreMoves(Span<Move> moves, Span<int> scores, int count, Move ttMove, int ply)
    {
#if ASTER_PROFILE
        long started = Stopwatch.GetTimestamp();
        try
        {
#endif
        Move counter = ply > 0 && previousPieces[ply - 1] >= 0
            ? counterMoves[previousPieces[ply - 1], previousMoves[ply - 1].To] : Move.None;
        for (int i = 0; i < count; i++)
        {
            Move move = moves[i];
            if (move == ttMove) scores[i] = 2_000_000;
            else if (move.IsCapture || move.Promotion != 0)
            {
                int victim = move.IsEnPassant ? 0 : board.Squares[move.To] % 6;
                int exchange = See.Evaluate(board, move);
                scores[i] = (exchange >= 0 ? 1_000_000 : 100_000) + (victim < 0 ? 0 : Evaluation.Material[victim] * 16)
                    - Evaluation.Material[board.Squares[move.From] % 6] + (move.Promotion == 0 ? 0 : Evaluation.Material[move.Promotion] * 16);
            }
            else if (move == killers[ply, 0]) scores[i] = 900_000;
            else if (move == killers[ply, 1]) scores[i] = 800_000;
            else if (move == counter) scores[i] = 700_000;
            else scores[i] = history[board.Side, move.From, move.To];
        }
#if ASTER_PROFILE
        }
        finally { SearchProfile.RecordOrdering(started); }
#endif
    }
    private static void SelectNext(Span<Move> moves, Span<int> scores, int index, int count)
    {
        int best = index;
        for (int i = index + 1; i < count; i++) if (scores[i] > scores[best]) best = i;
        (moves[index], moves[best]) = (moves[best], moves[index]);
        (scores[index], scores[best]) = (scores[best], scores[index]);
    }
}
