#if ASTER_PROFILE
using System.Diagnostics;

namespace Aster;

// Instrumented builds only. Normal builds resolve the search aliases directly
// to Evaluation/StaticExchange and contain none of these timers or counters.
internal static class SearchProfile
{
    private static long evaluationTicks, exchangeTicks, legalTicks, orderingTicks;
    private static long evaluationCalls, exchangeCalls, legalCalls, orderingCalls;
    private static long reducedSearches, reducedPlies, prunedQuietMoves;

    public static void Reset()
    {
        evaluationTicks = exchangeTicks = legalTicks = orderingTicks = 0;
        evaluationCalls = exchangeCalls = legalCalls = orderingCalls = 0;
        reducedSearches = reducedPlies = prunedQuietMoves = 0;
    }

    public static int Evaluate(Board board)
    {
        long started = Stopwatch.GetTimestamp();
        try { return Evaluation.Evaluate(board); }
        finally { evaluationTicks += Stopwatch.GetTimestamp() - started; evaluationCalls++; }
    }

    public static int Evaluate(Board board, Move move)
    {
        long started = Stopwatch.GetTimestamp();
        try { return StaticExchange.Evaluate(board, move); }
        finally { exchangeTicks += Stopwatch.GetTimestamp() - started; exchangeCalls++; }
    }

    public static void RecordLegal(long started) { legalTicks += Stopwatch.GetTimestamp() - started; legalCalls++; }
    public static void RecordOrdering(long started) { orderingTicks += Stopwatch.GetTimestamp() - started; orderingCalls++; }
    public static void RecordReduction(int reduction)
    {
        if (reduction <= 0) return;
        reducedSearches++; reducedPlies += reduction;
    }
    public static void RecordQuietPrune() => prunedQuietMoves++;

    public static object Snapshot() => new
    {
        evaluation = new { calls = evaluationCalls, milliseconds = Milliseconds(evaluationTicks) },
        legalMoveExistence = new { calls = legalCalls, milliseconds = Milliseconds(legalTicks) },
        moveOrdering = new { calls = orderingCalls, milliseconds = Milliseconds(orderingTicks) },
        staticExchange = new { calls = exchangeCalls, milliseconds = Milliseconds(exchangeTicks) },
        lateMoveReduction = new { reducedSearches, reducedPlies },
        lateQuietPruning = new { prunedQuietMoves },
        interpretation = "Instrumented timings include measurement overhead. Static exchange is mostly included in move ordering; categories overlap and must not be summed. Fixed-depth work, not playing strength."
    };
    private static double Milliseconds(long ticks) => Math.Round(ticks * 1000.0 / Stopwatch.Frequency, 3);
}
#endif
