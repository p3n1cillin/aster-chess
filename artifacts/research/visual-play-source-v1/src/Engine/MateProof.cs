using System.Numerics;

namespace Aster;

public sealed record MateStrategyProof(int Schema, bool Complete, string Reason, string Summary, string RootFen,
    int StrongSide, int RootDistance, int MaxPlies, int Visits, int NodeLimit, List<ProofNode> Nodes);

// Bounded proof search, separate from playing search. No selective reductions,
// null moves or heuristic cutoffs can establish a certificate. A strategy must
// cover every legal defense and terminate exclusively at real checkmate.
public static class MateProof
{
    private sealed class ProofLimitException : Exception;
    private sealed record Tree(string Fen, int Distance, List<(Move Move, Tree Child)> Children);

    public static MateStrategyProof Build(Board position, int strongSide, int maxPlies = 7,
        int nodeLimit = 50000, CancellationToken cancellation = default)
    {
        if ((uint)strongSide > 1) throw new ArgumentOutOfRangeException(nameof(strongSide));
        if (maxPlies is < 0 or > 7) throw new ArgumentOutOfRangeException(nameof(maxPlies));
        if (nodeLimit is < 1 or > 100000) throw new ArgumentOutOfRangeException(nameof(nodeLimit));
        Board board = position.Clone(); string rootFen = board.ToFen(); ulong rootKey = board.Key;
        int rootPly = board.Ply, visits = 0;
        var nodes = new List<ProofNode>();
        MateStrategyProof Result(bool complete, string reason, string summary, int distance = 0)
        {
            if (board.ToFen() != rootFen || board.Key != rootKey || board.Ply != rootPly)
                throw new InvalidOperationException("Proof search did not restore its root.");
            return new(1, complete, reason, summary, rootFen, strongSide, distance, maxPlies, visits, nodeLimit, nodes);
        }
        // Reject opposite-side check and rights inconsistent with the placement.
        // Ordinary FEN loading is also used for diagnostic setups; certificates
        // make the stronger claim that their roots obey standard position rules.
        int otherKing = BitOperations.TrailingZeroCount(board.Pieces[(board.Side ^ 1) * 6 + 5]);
        int ownKing = BitOperations.TrailingZeroCount(board.Pieces[board.Side * 6 + 5]), enemy = (board.Side ^ 1) * 6;
        ulong checkers = (Attacks.Pawn[board.Side, ownKing] & board.Pieces[enemy])
            | (Attacks.Knight[ownKing] & board.Pieces[enemy + 1])
            | (Attacks.Bishop(ownKing, board.Occupied) & (board.Pieces[enemy + 2] | board.Pieces[enemy + 4]))
            | (Attacks.Rook(ownKing, board.Occupied) & (board.Pieces[enemy + 3] | board.Pieces[enemy + 4]));
        if (board.IsAttacked(otherKing, board.Side)
            || BitOperations.PopCount(checkers) > 2
            || BitOperations.PopCount(board.Colors[0]) > 16 || BitOperations.PopCount(board.Colors[1]) > 16
            || BitOperations.PopCount(board.Pieces[0]) > 8 || BitOperations.PopCount(board.Pieces[6]) > 8
            || (board.EpSquare >= 0 && (board.Squares[board.EpSquare + (board.Side == 0 ? 8 : -8)] != -1 || board.HalfmoveClock != 0))
            || ((board.Castling & 1) != 0 && (board.Squares[4] != 5 || board.Squares[7] != 3))
            || ((board.Castling & 2) != 0 && (board.Squares[4] != 5 || board.Squares[0] != 3))
            || ((board.Castling & 4) != 0 && (board.Squares[60] != 11 || board.Squares[63] != 9))
            || ((board.Castling & 8) != 0 && (board.Squares[60] != 11 || board.Squares[56] != 9)))
            return Result(false, "invalid_position", "The certificate root is not a valid standard-chess position.");

        Tree? Visit(int remaining)
        {
            cancellation.ThrowIfCancellationRequested();
            if (visits >= nodeLimit) throw new ProofLimitException();
            visits++;
            Span<Move> legal = stackalloc Move[256]; int count = board.GenerateLegal(legal);
            if (count == 0)
                return board.InCheck && board.Side != strongSide ? new(board.ToFen(), 0, []) : null;
            // Mate takes precedence at the horizon and at rule50. Every other
            // drawn or exhausted node is unproved, never a winning leaf.
            if (remaining == 0 || board.HalfmoveClock >= 100 || board.IsRepetition() || board.InsufficientMaterial()) return null;
            bool choose = board.Side == strongSide;
            if (choose)
            {
                // Checks first improves discovery without omitting quiet mates.
                Span<int> priority = stackalloc int[256];
                for (int i = 0; i < count; i++)
                {
                    cancellation.ThrowIfCancellationRequested();
                    if (!board.TryMakeMove(legal[i])) throw new InvalidOperationException("Generated illegal proof move.");
                    try { priority[i] = (board.InCheck ? 4 : 0) + (legal[i].IsCapture ? 2 : 0) + (legal[i].Promotion != 0 ? 1 : 0); }
                    finally { board.UnmakeMove(); }
                }
                for (int i = 1; i < count; i++)
                {
                    Move move = legal[i]; int rank = priority[i], j = i;
                    while (j > 0 && priority[j - 1] < rank) { legal[j] = legal[j - 1]; priority[j] = priority[j - 1]; j--; }
                    legal[j] = move; priority[j] = rank;
                }
            }
            var children = new List<(Move, Tree)>(); int distance = 0;
            for (int i = 0; i < count; i++)
            {
                cancellation.ThrowIfCancellationRequested();
                if (!board.TryMakeMove(legal[i])) throw new InvalidOperationException("Generated illegal proof move.");
                Tree? child;
                try { child = Visit(remaining - 1); }
                finally { board.UnmakeMove(); }
                if (child == null)
                {
                    if (!choose) return null; // A single unproved defense prevents a guarantee.
                    continue;
                }
                children.Add((legal[i], child)); distance = Math.Max(distance, child.Distance + 1);
                if (choose) break;
            }
            return children.Count == 0 ? null : new(board.ToFen(), distance, children);
        }
        int Flatten(Tree tree)
        {
            cancellation.ThrowIfCancellationRequested();
            int id = nodes.Count; var edges = new List<ProofEdge>();
            nodes.Add(new(id, tree.Fen, tree.Distance, edges));
            foreach (var (move, child) in tree.Children) edges.Add(new(move.ToString(), Flatten(child)));
            return id;
        }
        try
        {
            cancellation.ThrowIfCancellationRequested();
            // An already terminal mate must precede history/clock claims.
            Tree? terminal = Visit(0);
            if (terminal != null)
            {
                _ = Flatten(terminal);
                return Result(true, "complete", "The defender is already checkmated.");
            }
            if (board.Ply != 0 && board.HalfmoveClock != 0)
                return Result(false, "prior_history", "A certificate requires a FEN history origin or a reset halfmove clock.");
            if ((long)board.HalfmoveClock + maxPlies >= 100)
                return Result(false, "rule50_boundary", "The requested mate bound does not fit the conservative fifty-move guard.");
            for (int bound = 1; bound <= maxPlies; bound++)
            {
                Tree? strategy = Visit(bound); if (strategy == null) continue;
                _ = Flatten(strategy);
                return Result(true, "complete", $"{(strongSide == 0 ? "White" : "Black")} can force checkmate within {strategy.Distance} plies. "
                    + $"The certificate covers every legal defensive reply in {nodes.Count} positions; every path ends in checkmate.", strategy.Distance);
            }
            return Result(false, "unproven_within_bound", $"No complete strategy was proved within {maxPlies} plies; this is not a claim that the position is drawn or lost.");
        }
        catch (ProofLimitException)
        { nodes.Clear(); return Result(false, "node_limit", "The work budget expired before a complete strategy was proved."); }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested)
        { nodes.Clear(); return Result(false, "cancelled", "The proof was cancelled before a complete strategy was exported."); }
    }
}
