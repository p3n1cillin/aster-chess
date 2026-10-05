using System.Diagnostics;

namespace Aster;

public sealed record RootMoveView(string Move, int? Score, string Bound, long Nodes, bool Searching);
public sealed record SearchView(int Depth, int Ply, string Fen, string[] Line, long Nodes,
    long MainNodes, long QuiescenceNodes, long BetaCutoffs, long TableCutoffs, long NullProbes,
    long ReducedMoves, long Milliseconds, long[] DestinationVisits, RootMoveView[] RootMoves, bool Finished);

// Optional observations only: no decisions, weights, bounds or search state are
// changed. A failing presentation sink disables itself rather than failing play.
public sealed class SearchVisualization(Action<SearchView> publish, int intervalMilliseconds = 80)
{
    private readonly Move[] line = new Move[Search.MaxPly];
    private readonly long[] destinations = new long[64];
    private readonly Dictionary<Move, RootMoveView> roots = [];
    private readonly Stopwatch clock = new();
    private long mainNodes, quiescenceNodes, betaCutoffs, tableCutoffs, nullProbes, reducedMoves, nextSample;
    private int depth;
    private bool enabled = true;

    internal void Start()
    {
        Array.Clear(line); Array.Clear(destinations); roots.Clear();
        mainNodes = quiescenceNodes = betaCutoffs = tableCutoffs = nullProbes = reducedMoves = nextSample = 0;
        depth = 0; enabled = true; clock.Restart();
    }
    internal void Iteration(int value) { depth = value; roots.Clear(); }
    internal void Enter(int ply, Move move) => line[ply] = move;
    internal void Leave(int ply) => line[ply] = Move.None;
    internal void BetaCutoff() => betaCutoffs++;
    internal void TableCutoff() => tableCutoffs++;
    internal void NullProbe() => nullProbes++;
    internal void Reduction(int amount) { if (amount > 0) reducedMoves++; }
    internal void RootStart(Move move, long nodes) => roots[move] = new(move.ToString(), null, "pending", -nodes, true);
    internal void RootEnd(Move move, int score, int alpha, int beta, long nodes)
    {
        long started = roots[move].Nodes;
        roots[move] = new(move.ToString(), score, score >= beta ? "lower" : score <= alpha ? "upper" : "exact", nodes + started, false);
    }
    internal void Visit(Board board, int ply, long nodes, bool quiescence)
    {
        if (quiescence) quiescenceNodes++; else mainNodes++;
        if (ply > 0 && line[ply - 1] != Move.None) destinations[line[ply - 1].To]++;
        // Checking the wall clock on every node would dominate short searches.
        if (enabled && (nodes == 1 || (nodes & 255) == 0) && clock.ElapsedMilliseconds >= nextSample)
        {
            Emit(board, ply, nodes, false);
            nextSample = clock.ElapsedMilliseconds + Math.Max(30, intervalMilliseconds);
        }
    }
    internal void Finish(Board board, long nodes) => Emit(board, 0, nodes, true);
    private void Emit(Board board, int ply, long nodes, bool finished)
    {
        if (!enabled) return;
        string[] moves = new string[ply];
        for (int i = 0; i < ply; i++) moves[i] = line[i] == Move.None ? "null" : line[i].ToString();
        var candidates = roots.Values.Select(row => row.Searching ? row with
        {
            Nodes = Math.Max(0, nodes + row.Nodes), Searching = !finished,
            Bound = finished ? "unfinished" : "pending"
        } : row).ToArray();
        var frame = new SearchView(depth, ply, board.ToFen(), moves, nodes, mainNodes, quiescenceNodes,
            betaCutoffs, tableCutoffs, nullProbes, reducedMoves, clock.ElapsedMilliseconds,
            (long[])destinations.Clone(), candidates, finished);
        try { publish(frame); }
        catch (Exception) { enabled = false; }
    }
}
