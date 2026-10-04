namespace Aster;

public sealed record ProofEdge(string Move, int To);
public sealed record ProofNode(int Id, string Fen, int Distance, List<ProofEdge> Edges);
public sealed record ProofAlternative(string Move, bool PreservesWin, int? RemainingPlies, string Reason);
public sealed record StrategyProof(bool Complete, string Reason, string Summary, string RootFen, int StrongSide,
    int RootDistance, int NodeLimit, List<ProofNode> Nodes, List<ProofAlternative> Alternatives);

// A concrete winning strategy DAG: choose one strong-side move, cover every
// defender reply, and end exclusively in actual checkmate. Distance decreases
// on every edge. Independent verification needs legal chess rules, no Aster table.
public static class EndgameProof
{
    private sealed class ProofLimitException : Exception;
    public static StrategyProof Build(Board position, int nodeLimit = 50000)
    {
        if (nodeLimit is < 1 or > 100000) throw new ArgumentOutOfRangeException(nameof(nodeLimit));
        var board = position.Clone(); string rootFen = board.ToFen();
        var nodes = new List<ProofNode>(); var alternatives = new List<ProofAlternative>();
        int strong = 0, distance = 0;
        StrategyProof Result(bool complete, string reason, string summary) =>
            new(complete, reason, summary, rootFen, strong, distance, nodeLimit, nodes, alternatives);
        if (!MajorMateBitbase.Probe(board, out strong, out bool won, out distance))
            return Result(false, "unsupported_material", "Strategy proofs currently cover king and queen/rook versus king.");
        if (!won) return Result(false, "theoretical_draw", "There is no forced mate in this theoretical endgame position.");
        if (board.HalfmoveClock + distance >= 100)
            return Result(false, "rule50_boundary", "The theoretical mate bound does not fit the conservative fifty-move guard.");
        if (board.Ply != 0 && board.HalfmoveClock != 0)
            return Result(false, "prior_history", "A full proof requires a FEN history origin or a just-reset halfmove clock.");
        Span<Move> rootMoves = stackalloc Move[256]; int rootCount = board.GenerateLegal(rootMoves);
        for (int i = 0; i < rootCount; i++)
        {
            Move move = rootMoves[i]; if (!board.TryMakeMove(move)) continue;
            try
            {
                bool childWon = MajorMateBitbase.Probe(board, out _, out bool childWin, out int childDistance) && childWin;
                alternatives.Add(new(move.ToString(), childWon, childWon ? childDistance : null,
                    !childWon ? "Allows a theoretical draw." : childDistance < distance
                        ? $"Reduces the mate bound from {distance} to {childDistance} plies."
                        : $"Keeps a win but leaves {childDistance} plies; it does not reduce the current bound."));
            }
            finally { board.UnmakeMove(); }
        }
        var visited = new Dictionary<ulong, int>();
        int Visit()
        {
            if (visited.TryGetValue(board.Key, out int known)) return known;
            if (nodes.Count >= nodeLimit) throw new ProofLimitException();
            if (!MajorMateBitbase.Probe(board, out _, out bool nodeWon, out int remaining) || !nodeWon)
                throw new InvalidOperationException("A strategy edge lost its winning invariant.");
            int id = nodes.Count; var edges = new List<ProofEdge>();
            nodes.Add(new(id, board.ToFen(), remaining, edges)); visited.Add(board.Key, id);
            Span<Move> legal = stackalloc Move[256]; int count = board.GenerateLegal(legal);
            if (count == 0)
            {
                if (!board.InCheck || remaining != 0) throw new InvalidOperationException("Strategy leaf is not checkmate.");
                return id;
            }
            bool choose = board.Side == strong;
            for (int i = 0; i < count; i++)
            {
                Move move = legal[i]; if (!board.TryMakeMove(move)) continue;
                try
                {
                    bool progress = MajorMateBitbase.Probe(board, out _, out bool childWon, out int next) && childWon && next < remaining;
                    if (!progress)
                    {
                        if (!choose) throw new InvalidOperationException("A legal defensive reply escaped the mate bound.");
                        continue;
                    }
                    edges.Add(new(move.ToString(), Visit()));
                }
                finally { board.UnmakeMove(); }
                if (choose && edges.Count != 0) break;
            }
            if (edges.Count == 0) throw new InvalidOperationException("No strategy continuation.");
            return id;
        }
        try { _ = Visit(); }
        catch (ProofLimitException) { return Result(false, "node_limit", "The complete strategy exceeds the certificate node limit."); }
        return Result(true, "complete", $"{(strong == 0 ? "White" : "Black")} can force checkmate within {distance} plies. "
            + $"The certificate covers every legal defensive reply in {nodes.Count} positions; every path ends in checkmate.");
    }
}
