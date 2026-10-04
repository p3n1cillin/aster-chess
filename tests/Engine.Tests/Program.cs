using Aster;
using System.Diagnostics;

int passed = 0, failed = 0;
void Test(string name, Action action)
{
    try { action(); Console.WriteLine($"PASS {name}"); passed++; }
    catch (Exception error) { Console.WriteLine($"FAIL {name}: {error.Message}"); failed++; }
}
void Equal<T>(T expected, T actual) where T : notnull
{
    if (!EqualityComparer<T>.Default.Equals(expected, actual)) throw new Exception($"Expected {expected}, got {actual}");
}
void Require(bool condition, string message)
{
    if (!condition) throw new Exception(message);
}
void Play(Board board, params string[] moves)
{
    foreach (string move in moves) Require(board.TryMakeMove(board.ParseMove(move)), $"Could not play {move}");
}
SearchResult Find(Board board, int depth = 4, SearchLimits? limits = null, CancellationToken cancellation = default) =>
    new Search(new TranspositionTable(8)).Run(board, limits ?? new SearchLimits(depth), cancellation);

var positions = new (string Name, string Fen, int Depth, long Nodes)[]
{
    ("startpos", Board.StartFen, 5, 4865609),
    ("kiwipete", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 4, 4085603),
    ("rook and pawn endgame", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 4, 43238),
    ("promotions and castling", "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", 4, 422333),
    ("promotion checks", "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", 3, 62379),
    ("middlegame pins", "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10", 3, 89890)
};
foreach (var test in positions)
    Test($"perft {test.Name} depth {test.Depth}", () =>
    {
        var board = new Board(test.Fen);
        Equal(test.Nodes, Perft.Count(board, test.Depth)); Equal(test.Fen, board.ToFen());
    });

Test("perft depth zero and invalid depth", () =>
{
    Equal(1L, Perft.Count(new Board(), 0));
    try { Perft.Count(new Board(), -1); throw new Exception("Negative depth accepted"); } catch (ArgumentOutOfRangeException) { }
});
Test("all legal moves restore board, hash, evaluation, and bitboards", () =>
{
    Span<Move> legal = stackalloc Move[256];
    foreach (var test in positions)
    {
        var board = new Board(test.Fen);
        ulong key = board.Key; int mg = board.MgScore, eg = board.EgScore, phase = board.Phase;
        int[] squares = (int[])board.Squares.Clone(); ulong[] pieces = (ulong[])board.Pieces.Clone();
        int count = board.GenerateLegal(legal);
        for (int i = 0; i < count; i++)
        {
            Require(board.TryMakeMove(legal[i]), "Generated illegal move");
            var rebuilt = new Board(board.ToFen());
            Equal(rebuilt.Key, board.Key); Equal(rebuilt.MgScore, board.MgScore); Equal(rebuilt.EgScore, board.EgScore);
            board.UnmakeMove();
            Equal(key, board.Key); Equal(mg, board.MgScore); Equal(eg, board.EgScore); Equal(phase, board.Phase);
            Require(squares.SequenceEqual(board.Squares) && pieces.SequenceEqual(board.Pieces), "Undo corrupted board");
            Equal(test.Fen, board.ToFen());
        }
    }
});
Test("random playout incremental state and full undo", () =>
{
    var random = new Random(20261003);
    Span<Move> moves = stackalloc Move[256];
    for (int game = 0; game < 20; game++)
    {
        var board = new Board();
        for (int ply = 0; ply < 160; ply++)
        {
            int count = board.GenerateLegal(moves); if (count == 0) break;
            board.TryMakeMove(moves[random.Next(count)]);
            var rebuilt = new Board(board.ToFen());
            Equal(rebuilt.Key, board.Key); Equal(rebuilt.MgScore, board.MgScore);
            Equal(rebuilt.EgScore, board.EgScore); Equal(rebuilt.Phase, board.Phase);
            Require(rebuilt.Pieces.SequenceEqual(board.Pieces), "Piece bitboards diverged");
        }
        while (board.Ply > 0) board.UnmakeMove();
        Equal(Board.StartFen, board.ToFen()); Equal(new Board().Key, board.Key);
    }
});
Test("classical evaluation respects color and rank symmetry", () =>
{
    void Check(Board board)
    {
        string fen = board.ToFen();
        string[] fields = fen.Split(' ');
        fields[0] = string.Join('/', fields[0].Split('/').Reverse()
            .Select(rank => new string(rank.Select(piece => char.IsLetter(piece)
                ? (char.IsUpper(piece) ? char.ToLowerInvariant(piece) : char.ToUpperInvariant(piece))
                : piece).ToArray())));
        fields[1] = fields[1] == "w" ? "b" : "w";
        fields[2] = new string(fields[2].Select(right => char.IsUpper(right)
            ? char.ToLowerInvariant(right) : char.ToUpperInvariant(right)).ToArray());
        if (fields[3] != "-") fields[3] = $"{fields[3][0]}{9 - (fields[3][1] - '0')}";
        var mirrored = new Board(string.Join(' ', fields));
        ulong key = board.Key;
        Equal(Evaluation.EvaluateClassical(board), Evaluation.EvaluateClassical(mirrored));
        Equal(fen, board.ToFen()); Equal(key, board.Key);
    }
    foreach (var position in positions) Check(new Board(position.Fen));
    var random = new Random(20261008);
    Span<Move> moves = stackalloc Move[256];
    for (int game = 0; game < 10; game++)
    {
        var board = new Board();
        for (int ply = 0; ply < 120; ply++)
        {
            Check(board);
            int count = board.GenerateLegal(moves); if (count == 0) break;
            Require(board.TryMakeMove(moves[random.Next(count)]), "Generated illegal move");
        }
    }
});
Test("geometric threat features distinguish loose and defended lower-value attacks", () =>
{
    Span<int> features = stackalloc int[7], repeated = stackalloc int[7];
    foreach (var (fen, expected) in new (string, int[])[]
    {
        (Board.StartFen, [0, 0, 0, 0, 0, 0, 0]),
        ("7k/8/8/8/8/r7/8/Q5K1 w - - 0 1", [0, 0, 1, -1, 0, 0, 0]),
        ("7k/8/8/8/8/r7/1B6/Q5K1 w - - 0 1", [0, 0, 1, 0, 0, 0, -1])
    })
    {
        var board = new Board(fen); ulong key = board.Key;
        ThreatEvaluation.ExtractFeatures(board, features);
        Require(features.SequenceEqual(expected), "Incorrect threat classification");
        int correction = ThreatEvaluation.WhiteCorrection(board, features);
        board.MakeNullMove();
        try
        {
            ThreatEvaluation.ExtractFeatures(board, repeated);
            Require(repeated.SequenceEqual(expected), "Feature depends on turn");
            Equal(correction, ThreatEvaluation.WhiteCorrection(board, repeated));
        }
        finally { board.UnmakeMove(); }
        Equal(fen, board.ToFen()); Equal(key, board.Key);
    }
});
Test("legal-move existence agrees with complete generation and preserves state", () =>
{
    string[] special = [
        "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1",
        "k7/n1K5/8/8/8/8/8/R7 b - - 0 1", "k7/nnK5/8/8/8/8/8/R6B b - - 0 1",
        "r7/8/8/8/8/8/B1k5/K7 w - - 0 1", "8/8/8/r4pPK/8/8/8/4k3 w - f6 0 1",
        "8/5P1k/5K2/8/8/8/8/8 w - - 0 1"
    ];
    Span<Move> moves = stackalloc Move[256];
    void Check(Board board, Span<Move> buffer)
    {
        string before = board.ToFen(); ulong key = board.Key; int ply = board.Ply;
        Equal(board.GenerateLegal(buffer) > 0, board.HasAnyLegalMove());
        Equal(before, board.ToFen()); Equal(key, board.Key); Equal(ply, board.Ply);
    }
    foreach (string fen in special) Check(new Board(fen), moves);
    var random = new Random(20261008);
    for (int game = 0; game < 30; game++)
    {
        var board = new Board();
        for (int ply = 0; ply < 160; ply++)
        {
            Check(board, moves);
            int count = board.GenerateLegal(moves); if (count == 0) break;
            Require(board.TryMakeMove(moves[random.Next(count)]), "Illegal generated move");
        }
    }
});
Test("en passant cannot expose horizontal rook check", () =>
{
    var board = new Board("8/8/8/r4pPK/8/8/8/4k3 w - f6 0 1");
    Span<Move> moves = stackalloc Move[256]; int count = board.GenerateLegal(moves);
    Require(!moves[..count].ToArray().Any(m => m.ToString() == "g5f6"), "Illegal pinned en passant allowed");
    Equal(new Board("8/8/8/r4pPK/8/8/8/4k3 w - - 0 1").Key, board.Key);
});
Test("en passant hash only when legally available", () =>
{
    Equal(new Board("4k3/8/8/3p4/8/8/8/4K3 w - d6 0 1").Key,
        new Board("4k3/8/8/3p4/8/8/8/4K3 w - - 0 1").Key);
    Require(new Board("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1").Key !=
        new Board("4k3/8/8/3pP3/8/8/8/4K3 w - - 0 1").Key, "Legal en passant missing from hash");
});
Test("castling cannot cross attacked square", () =>
{
    var board = new Board("4kr2/8/8/8/8/8/8/4K2R w K - 0 1");
    Span<Move> moves = stackalloc Move[256]; int count = board.GenerateLegal(moves);
    Require(!moves[..count].ToArray().Any(m => m.IsCastle), "Castling through check allowed");
});
Test("underpromotion notation and undo", () =>
{
    var board = new Board("7k/P7/8/8/8/8/8/7K w - - 0 1");
    foreach (string promotion in new[] { "a7a8n", "a7a8b", "a7a8r", "a7a8q" })
    {
        Move move = board.ParseMove(promotion); Equal(promotion, move.ToString());
        board.TryMakeMove(move); board.UnmakeMove(); Equal("7k/P7/8/8/8/8/8/7K w - - 0 1", board.ToFen());
    }
});
Test("threefold requires three occurrences outside search", () =>
{
    var board = new Board(); Play(board, "g1f3", "g8f6", "f3g1", "f6g8");
    Require(!board.IsRepetition(), "Twofold treated as threefold");
    Require(board.IsRepetition(0), "Search cycle not detected");
    var clone = board.Clone(); Play(clone, "g1f3", "g8f6", "f3g1", "f6g8");
    Require(clone.IsRepetition(), "Threefold not detected after clone");
    Require(!board.IsRepetition(), "Clone mutated original");
});
Test("null move preserves history and incremental state", () =>
{
    var board = new Board(); Play(board, "e2e4", "g8f6");
    string fen = board.ToFen(); ulong key = board.Key;
    board.MakeNullMove(); Equal(1, board.Side); Require(!board.IsRepetition(0), "Null move manufactured repetition");
    board.UnmakeMove(); Equal(fen, board.ToFen()); Equal(key, board.Key);
});
Test("insufficient material and opposite color bishops", () =>
{
    Require(new Board("7k/8/8/8/8/8/8/7K w - - 0 1").InsufficientMaterial(), "K vs K not draw");
    Require(new Board("7k/8/8/8/8/8/6B1/7K w - - 0 1").InsufficientMaterial(), "KB vs K not draw");
    Require(!new Board("7k/8/8/8/8/8/5NN1/7K w - - 0 1").InsufficientMaterial(), "KNN vs K can have a mate position");
    Require(!new Board("5b1k/8/8/8/8/8/6B1/7K w - - 0 1").InsufficientMaterial(), "Opposite color bishops can have a mate position");
});
Test("mate in one and terminal mate", () =>
{
    var board = new Board("6k1/5ppp/8/8/8/8/5PPP/3Q2K1 w - - 0 1");
    SearchResult result = Find(board);
    Equal("d1d8", result.BestMove.ToString()); Equal(Search.Mate - 1, result.Score);
    Play(board, "d1d8"); result = Find(board);
    Equal(Move.None, result.BestMove); Equal(-Search.Mate, result.Score);
});
Test("checkmate takes precedence over rule-50 draw", () =>
{
    var board = new Board("3Q2k1/5ppp/8/8/8/8/5PPP/6K1 b - - 100 1");
    SearchResult result = Find(board); Equal(-Search.Mate, result.Score); Equal(Move.None, result.BestMove);
});
Test("stalemate is scored as draw", () =>
{
    var board = new Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1");
    SearchResult result = Find(board); Equal(0, result.Score); Equal(Move.None, result.BestMove);
});
Test("wins hanging queen", () =>
{
    var board = new Board("4k3/8/8/8/3q4/2P5/8/4K3 w - - 0 1");
    Equal("c3d4", Find(board, 4).BestMove.ToString());
});
Test("search leaves root intact and PV is legal", () =>
{
    var board = new Board(); string fen = board.ToFen(); ulong key = board.Key;
    SearchResult result = Find(board, 6);
    Equal(fen, board.ToFen()); Equal(key, board.Key); Equal(0, board.Ply);
    Require(result.Depth == 6 && result.Nodes > 0, "Incomplete search");
    foreach (Move move in result.Pv) Play(board, move.ToString());
});
Test("node limit returns legal fallback and restores board", () =>
{
    var board = new Board(); SearchResult result = Find(board, limits: new SearchLimits(Nodes: 1));
    Require(result.Nodes <= 1, "Exceeded node limit"); _ = board.ParseMove(result.BestMove.ToString());
    Equal(Board.StartFen, board.ToFen());
});
Test("pre-cancelled search and searchmoves fallback", () =>
{
    var board = new Board(); Move only = board.ParseMove("e2e4");
    SearchResult result = Find(board, limits: new SearchLimits(SearchMoves: [only]), cancellation: new CancellationToken(true));
    Equal(only, result.BestMove); Equal(Board.StartFen, board.ToFen());
});
Test("hard time limit and asynchronous cancellation", () =>
{
    var board = new Board(); var timer = Stopwatch.StartNew();
    SearchResult result = Find(board, limits: new SearchLimits(HardMilliseconds: 30));
    Require(timer.ElapsedMilliseconds < 1500, "Hard limit not respected"); _ = board.ParseMove(result.BestMove.ToString());
    using var token = new CancellationTokenSource(30);
    result = Find(board, limits: new SearchLimits(Infinite: true), cancellation: token.Token);
    Require(timer.ElapsedMilliseconds < 3000, "Cancellation not respected"); Equal(Board.StartFen, board.ToFen());
});
Test("transposition table mate distance and rule-50 key", () =>
{
    var table = new TranspositionTable(1);
    table.Store(42, new Move(1, 2), Search.Mate - 10, 5, Bound.Exact, 3);
    Require(table.Probe(42, 7, out _, out int score, out int depth, out Bound bound), "TT miss");
    Equal(Search.Mate - 14, score); Equal(5, depth); Equal(Bound.Exact, bound);
    var board = new Board(); var nearDraw = new Board(Board.StartFen.Replace("0 1", "99 1"));
    Equal(board.Key, nearDraw.Key); Require(board.SearchKey != nearDraw.SearchKey, "Rule-50 keys collide");
    table.Clear(); Require(!table.Probe(42, 0, out _, out _, out _, out _), "TT clear failed");
});
Test("horizon cache preserves deeper entries and signed mate distances", () =>
{
    var table = new TranspositionTable(1);
    foreach (Bound original in new[] { Bound.Exact, Bound.Lower, Bound.Upper })
    {
        table.Clear();
        table.Store(42, new Move(1, 2), 120, 6, original, 0);
        foreach (Bound horizon in new[] { Bound.Exact, Bound.Lower, Bound.Upper })
        {
            table.Store(42, new Move(2, 3), -90, 0, horizon, 0);
            Require(table.Probe(42, 0, out Move move, out int score, out int depth, out Bound bound), "Deep entry lost");
            Equal(new Move(1, 2), move); Equal(120, score); Equal(6, depth); Equal(original, bound);
        }
    }
    table.Clear(); table.Store(42, new Move(2, 3), -Search.Mate + 10, 0, Bound.Exact, 3);
    Require(table.Probe(42, 7, out _, out int mate, out int qDepth, out _), "Horizon entry missing");
    Equal(-Search.Mate + 14, mate); Equal(0, qDepth);
});
Test("warm search cache preserves terminal rules, history and legal PV", () =>
{
    var table = new TranspositionTable(8);
    var search = new Search(table);
    foreach (string fen in new[] { Board.StartFen,
        "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",
        "7k/6Q1/6K1/8/8/8/8/8 b - - 100 1",
        "8/5P1k/5K2/8/8/8/8/8 w - - 0 1",
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 99 1" })
    {
        var board = new Board(fen);
        SearchResult cold = search.Run(board, new SearchLimits(4));
        SearchResult warm = search.Run(board, new SearchLimits(4));
        Equal(cold.Score, warm.Score); Equal(fen, board.ToFen());
        foreach (Move move in warm.Pv)
            Require(board.TryMakeMove(move), "Warm-cache PV contains illegal move");
    }
    var repeated = new Board();
    Play(repeated, "g1f3", "g8f6", "f3g1", "f6g8", "g1f3", "g8f6", "f3g1", "f6g8");
    string before = repeated.ToFen();
    Equal(0, search.Run(repeated, new SearchLimits(4)).Score); Equal(before, repeated.ToFen());
});
Test("static exchange handles wins, losses, pins, and promotions", () =>
{
    var cases = new (string Fen, string Move, int Score)[]
    {
        ("4k3/8/8/8/3q4/2P5/8/4K3 w - - 0 1", "c3d4", 950),
        ("3rk3/8/8/8/3p4/2P5/8/4K3 w - - 0 1", "c3d4", 0),
        ("3rk3/8/8/8/3p4/8/8/3QK3 w - - 0 1", "d1d4", -850),
        ("4k3/3pr3/2B5/8/8/8/8/K2RR3 w - - 0 1", "c6d7", 100),
        ("7k/4P3/8/8/8/8/8/7K w - - 0 1", "e7e8q", 850),
        ("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1", "e5d6", 100)
    };
    foreach (var test in cases)
    {
        var board = new Board(test.Fen);
        Equal(test.Score, StaticExchange.Evaluate(board, board.ParseMove(test.Move)));
        Equal(test.Fen, board.ToFen());
    }
});
Test("static exchange is safe on pseudo-legal king moves", () =>
{
    var random = new Random(147);
    Span<Move> moves = stackalloc Move[256];
    Span<Move> legal = stackalloc Move[256];
    for (int game = 0; game < 8; game++)
    {
        var board = new Board();
        for (int ply = 0; ply < 100; ply++)
        {
            int count = board.GeneratePseudoLegal(moves);
            for (int i = 0; i < count; i++)
                if (moves[i].IsCapture || moves[i].Promotion != 0) _ = StaticExchange.Evaluate(board, moves[i]);
            count = board.GenerateLegal(legal); if (count == 0) break;
            board.TryMakeMove(legal[random.Next(count)]);
        }
    }
});

Test("neural accumulator equals independent scalar rebuild across special moves", () =>
{
    const int hidden = 32;
    var rng = new Random(20261004);
    short[] linear = new short[768], bias = new short[hidden], weights = new short[768 * hidden], output = new short[hidden];
    for (int i = 0; i < linear.Length; i++) linear[i] = (short)rng.Next(-1000, 1001);
    for (int i = 0; i < hidden; i++) { bias[i] = (short)rng.Next(30, 200); output[i] = (short)rng.Next(-3000, 3001); }
    for (int i = 0; i < weights.Length; i++) weights[i] = (short)rng.Next(-100, 101);
    var network = new NeuralNetwork(hidden, linear, bias, weights, output);
    int Reference(Board board)
    {
        int[] sums = new int[hidden * 2]; int[] lin = new int[2];
        for (int perspective = 0; perspective < 2; perspective++)
        {
            for (int i = 0; i < hidden; i++) sums[perspective * hidden + i] = bias[i];
            for (int square = 0; square < 64; square++)
            {
                int piece = board.Squares[square]; if (piece < 0) continue;
                int feature = (perspective == 0 ? piece : (piece < 6 ? piece + 6 : piece - 6)) * 64
                    + (perspective == 0 ? square : (7 - square / 8) * 8 + square % 8);
                lin[perspective] += linear[feature];
                for (int i = 0; i < hidden; i++) sums[perspective * hidden + i] += weights[feature * hidden + i];
            }
        }
        long dot = 0;
        for (int i = 0; i < hidden; i++) dot += (long)(Math.Clamp(sums[i], 0, 256) - Math.Clamp(sums[hidden + i], 0, 256)) * output[i];
        return (lin[0] - lin[1]) / 2 + (int)(dot / 65536);
    }
    Span<Move> moves = stackalloc Move[256];
    foreach (string fen in positions.Select(p => p.Fen).Append("7k/P7/8/8/8/8/8/7K w - - 0 1")
        .Append("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1"))
    {
        var board = new Board(fen, network); Equal(Reference(board), board.Neural!.WhiteScore);
        int count = board.GenerateLegal(moves);
        for (int i = 0; i < count; i++)
        {
            int before = board.Neural.WhiteScore;
            board.TryMakeMove(moves[i]); Equal(Reference(board), board.Neural.WhiteScore);
            Equal(Reference(board), network.EvaluateFromScratch(board));
            var clone = board.Clone(); Equal(Reference(clone), clone.Neural!.WhiteScore);
            board.UnmakeMove(); Equal(before, board.Neural.WhiteScore);
        }
        for (int ply = 0; ply < 100; ply++)
        {
            int n = board.GenerateLegal(moves); if (n == 0) break;
            board.TryMakeMove(moves[rng.Next(n)]); Equal(Reference(board), board.Neural.WhiteScore);
            board.MakeNullMove(); Equal(Reference(board), board.Neural.WhiteScore); board.UnmakeMove();
        }
        while (board.Ply > 0) board.UnmakeMove();
        Equal(fen, board.ToFen()); Equal(Reference(board), board.Neural.WhiteScore);
        board.LoadFen(Board.StartFen); Equal(Reference(board), board.Neural.WhiteScore);
    }
});
Test("king-context neural inference survives bucket changes, undo, and serialization", () =>
{
    const int hidden = 16, features = 768 * 17;
    var random = new Random(20261013);
    short[] linear = new short[features], bias = new short[hidden], weights = new short[features * hidden], output = new short[hidden];
    for (int i = 0; i < features; i++) linear[i] = (short)random.Next(-200, 201);
    for (int i = 0; i < hidden; i++) { bias[i] = (short)random.Next(40, 200); output[i] = (short)random.Next(-3000, 3001); }
    for (int i = 0; i < weights.Length; i++) weights[i] = (short)random.Next(-40, 41);
    int Reference(Board board)
    {
        int[] sums = new int[hidden * 2], lin = new int[2];
        for (int perspective = 0; perspective < 2; perspective++)
        {
            int king = Array.IndexOf(board.Squares, perspective * 6 + 5);
            int kingRank = perspective == 0 ? king / 8 : 7 - king / 8;
            int bucket = kingRank / 2 * 4 + king % 8 / 2;
            for (int i = 0; i < hidden; i++) sums[perspective * hidden + i] = bias[i];
            for (int square = 0; square < 64; square++)
            {
                int piece = board.Squares[square]; if (piece < 0) continue;
                int relative = perspective == 0 ? piece : piece < 6 ? piece + 6 : piece - 6;
                int rank = perspective == 0 ? square / 8 : 7 - square / 8;
                int raw = relative * 64 + rank * 8 + square % 8;
                int context = 768 + bucket * 768 + raw;
                lin[perspective] += linear[raw] + linear[context];
                for (int i = 0; i < hidden; i++) sums[perspective * hidden + i] += weights[raw * hidden + i] + weights[context * hidden + i];
            }
        }
        long dot = 0;
        for (int i = 0; i < hidden; i++) dot += (long)(Math.Clamp(sums[i], 0, 256) - Math.Clamp(sums[hidden + i], 0, 256)) * output[i];
        return (lin[0] - lin[1]) / 2 + (int)(dot / 65536);
    }
    Span<Move> contextMoves = stackalloc Move[256];
    foreach (bool hybrid in new[] { false, true })
    {
        var model = new NeuralNetwork(hidden, linear, bias, weights, output, classicalBase: hybrid, kingContext: true);
        foreach (string fen in positions.Select(p => p.Fen).Append("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
            .Append("7k/P7/8/8/8/8/8/7K w - - 0 1"))
        {
            var board = new Board(fen, model);
            Equal(Reference(board), board.Neural!.WhiteScore);
            int count = board.GenerateLegal(contextMoves);
            for (int i = 0; i < count; i++)
            {
                int before = board.Neural.WhiteScore;
                Require(board.TryMakeMove(contextMoves[i]), "Generated illegal move");
                Equal(Reference(board), board.Neural.WhiteScore);
                Equal(Reference(board), board.Clone().Neural!.WhiteScore);
                board.UnmakeMove(); Equal(before, board.Neural.WhiteScore);
                Require(board.TryMakeMove(contextMoves[i]), "Generated illegal move");
                board.UnmakeMove(); Equal(before, board.Neural.WhiteScore);
            }
            for (int ply = 0; ply < 120; ply++)
            {
                int n = board.GenerateLegal(contextMoves); if (n == 0) break;
                Require(board.TryMakeMove(contextMoves[random.Next(n)]), "Generated illegal move");
                Equal(Reference(board), board.Neural.WhiteScore);
                board.MakeNullMove(); Equal(Reference(board), board.Neural.WhiteScore); board.UnmakeMove();
            }
            while (board.Ply > 0) { board.UnmakeMove(); Equal(Reference(board), board.Neural.WhiteScore); }
            Equal(fen, board.ToFen()); board.LoadFen(Board.StartFen); Equal(Reference(board), board.Neural.WhiteScore);
        }
        var walking = new Board("4k3/8/8/8/8/8/8/4K2R w - - 0 1", model);
        foreach (string move in new[] { "e1d1", "e8d8", "d1e1", "d8e8" })
        { Play(walking, move); Equal(Reference(walking), walking.Neural!.WhiteScore); }
        var searchBoard = new Board(positions[1].Fen, model); ulong key = searchBoard.Key;
        _ = Find(searchBoard, limits: new SearchLimits(Nodes: 5000));
        Equal(key, searchBoard.Key); Equal(positions[1].Fen, searchBoard.ToFen()); Equal(Reference(searchBoard), searchBoard.Neural!.WhiteScore);
        string path = Path.GetTempFileName();
        try
        {
            model.Save(path); var loaded = NeuralNetwork.Load(path);
            Require(loaded.HasKingContext, "King context flag lost"); Equal(hybrid, loaded.ClassicalBase); Equal(features, loaded.Features);
            Equal(Reference(walking), loaded.EvaluateFromScratch(walking));
            using (var file = File.OpenWrite(path)) { file.Position = 12; using var writer = new BinaryWriter(file); writer.Write(768); }
            try { NeuralNetwork.Load(path); throw new Exception("Wrong context dimensions accepted"); } catch (FormatException) { }
        }
        finally { File.Delete(path); }
    }
});
Test("turn-aware neural output survives null moves, cache reuse, and special moves", () =>
{
    const int hidden = 16, features = 768 * 17;
    var rng = new Random(20261018);
    short[] linear = new short[features], bias = new short[hidden], weights = new short[features * hidden], output = new short[hidden * 2];
    for (int i = 0; i < features; i++) linear[i] = (short)rng.Next(-200, 201);
    for (int i = 0; i < hidden; i++) bias[i] = (short)rng.Next(40, 200);
    for (int i = 0; i < weights.Length; i++) weights[i] = (short)rng.Next(-40, 41);
    for (int i = 0; i < output.Length; i++) output[i] = (short)rng.Next(-3000, 3001);
    int Reference(Board b, int side, bool squared)
    {
        int[] acc = new int[hidden * 2], lin = new int[2];
        for (int perspective = 0; perspective < 2; perspective++)
        {
            int king = Array.IndexOf(b.Squares, perspective * 6 + 5);
            int bucket = (perspective == 0 ? king / 8 : 7 - king / 8) / 2 * 4 + king % 8 / 2;
            for (int i = 0; i < hidden; i++) acc[perspective * hidden + i] = bias[i];
            for (int square = 0; square < 64; square++)
            {
                int piece = b.Squares[square]; if (piece < 0) continue;
                int relative = perspective == 0 ? piece : piece < 6 ? piece + 6 : piece - 6;
                int rank = perspective == 0 ? square / 8 : 7 - square / 8;
                int raw = relative * 64 + rank * 8 + square % 8, context = 768 * (bucket + 1) + raw;
                lin[perspective] += linear[raw] + linear[context];
                for (int i = 0; i < hidden; i++) acc[perspective * hidden + i] += weights[raw * hidden + i] + weights[context * hidden + i];
            }
        }
        long dot = 0;
        for (int i = 0; i < hidden; i++)
        {
            int own = Math.Clamp(acc[side * hidden + i], 0, 256), other = Math.Clamp(acc[(1 - side) * hidden + i], 0, 256);
            if (squared) { own = own * own / 256; other = other * other / 256; }
            dot += (long)own * output[i] + (long)other * output[i + hidden];
        }
        return (lin[0] - lin[1]) / 2 + (int)((side == 0 ? dot : -dot) / 65536);
    }
    Span<Move> moves = stackalloc Move[256];
    foreach (bool hybrid in new[] { false, true })
    foreach (bool squared in new[] { false, true })
    {
        var model = new NeuralNetwork(hidden, linear, bias, weights, output, classicalBase: hybrid, kingContext: true, turnOutput: true, squaredActivation: squared);
        void Check(Board b)
        {
            for (int side = 0; side < 2; side++) Equal(Reference(b, side, squared), b.Neural!.WhiteScoreForSide(side));
            int white = Reference(b, b.Side, squared);
            Equal(white, model.EvaluateFromScratch(b));
            int expected = hybrid ? Evaluation.EvaluateClassical(b) + (b.Side == 0 ? 1 : -1) * Math.Clamp(white, -250, 250)
                : (b.Side == 0 ? white : -white) + 12;
#if ASTER_KPK || ASTER_CONVERSION
            if (KpkBitbase.TryEvaluate(b, out int exact)) expected = exact;
#endif
#if ASTER_CONVERSION
            if (MajorMateBitbase.TryEvaluate(b, out int major)) expected = major;
#endif
            Equal(Math.Clamp(expected, -28000, 28000), Evaluation.Evaluate(b));
        }
        foreach (string fen in positions.Select(p => p.Fen).Append("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1"))
        {
            var b = new Board(fen, model); Check(b);
            int count = b.GenerateLegal(moves);
            for (int i = 0; i < count; i++)
            {
                Require(b.TryMakeMove(moves[i]), "Generated illegal move"); Check(b); Check(b.Clone());
                b.UnmakeMove(); Check(b);
            }
            for (int ply = 0; ply < 80; ply++)
            {
                b.MakeNullMove(); Check(b); b.UnmakeMove(); Check(b);
                int n = b.GenerateLegal(moves); if (n == 0) break;
                Require(b.TryMakeMove(moves[rng.Next(n)]), "Generated illegal move"); Check(b);
            }
            while (b.Ply > 0) { b.UnmakeMove(); Check(b); }
            Equal(fen, b.ToFen());
            _ = Find(b, limits: new SearchLimits(Nodes: 5000)); Check(b); Equal(fen, b.ToFen());
        }
        string path = Path.GetTempFileName();
        try
        {
            model.Save(path); var loaded = NeuralNetwork.Load(path);
            Require(loaded.HasTurnOutput && loaded.HasKingContext, "Turn-aware flags lost"); Equal(hybrid, loaded.ClassicalBase);
            Equal(squared, loaded.HasSquaredActivation);
            var b = new Board(Board.StartFen, loaded); Check(b);
            b.MakeNullMove(); Check(b); b.UnmakeMove(); Check(b);
            File.AppendAllText(path, "extra");
            try { NeuralNetwork.Load(path); throw new Exception("Extra turn-output payload accepted"); } catch (FormatException) { }
        }
        finally { File.Delete(path); }
    }
});
Test("turn-aware neural output keeps 64-bit sums and separate turn caches", () =>
{
    foreach (int hidden in new[] { 8, 256 })
    foreach (bool squared in new[] { false, true })
    {
        var model = new NeuralNetwork(hidden, new short[768 * 17], Enumerable.Repeat((short)256, hidden).ToArray(),
            new short[768 * 17 * hidden], Enumerable.Repeat(short.MinValue, hidden * 2).ToArray(), kingContext: true, turnOutput: true, squaredActivation: squared);
        var b = new Board(network: model);
        Equal(-hidden * 256, b.Neural!.WhiteScoreForSide(0)); Equal(hidden * 256, b.Neural.WhiteScoreForSide(1));
        Equal(-hidden * 256, b.Neural.WhiteScoreForSide(0));
        b.MakeNullMove(); Equal(hidden * 256, model.EvaluateFromScratch(b)); b.UnmakeMove();
        Equal(Math.Max(-28000, -hidden * 256 + 12), Evaluation.Evaluate(b));
    }
});
Test("phase output matches scalar rebuild through phase changes, null moves and undo", () =>
{
    const int hidden = 16, features = 768 * 17;
    var rng = new Random(20261112);
    short[] linear = new short[features], bias = new short[hidden], weights = new short[features * hidden], output = new short[hidden * 4];
    for (int i = 0; i < features; i++) linear[i] = (short)rng.Next(-200, 201);
    for (int i = 0; i < hidden; i++) bias[i] = (short)rng.Next(40, 200);
    for (int i = 0; i < weights.Length; i++) weights[i] = (short)rng.Next(-40, 41);
    for (int i = 0; i < output.Length; i++) output[i] = (short)rng.Next(-30000, 30001);
    int Reference(Board b, int side, int phase)
    {
        int[] acc = new int[hidden * 2], lin = new int[2];
        for (int perspective = 0; perspective < 2; perspective++)
        {
            int king = Array.IndexOf(b.Squares, perspective * 6 + 5);
            int bucket = (perspective == 0 ? king / 8 : 7 - king / 8) / 2 * 4 + king % 8 / 2;
            for (int i = 0; i < hidden; i++) acc[perspective * hidden + i] = bias[i];
            for (int square = 0; square < 64; square++)
            {
                int piece = b.Squares[square]; if (piece < 0) continue;
                int relative = perspective == 0 ? piece : (piece + 6) % 12;
                int raw = relative * 64 + (perspective == 0 ? square : (7 - square / 8) * 8 + square % 8);
                int context = 768 * (bucket + 1) + raw;
                lin[perspective] += linear[raw] + linear[context];
                for (int i = 0; i < hidden; i++) acc[perspective * hidden + i] += weights[raw * hidden + i] + weights[context * hidden + i];
            }
        }
        long mg = 0, eg = 0;
        for (int i = 0; i < hidden; i++)
        {
            int own = Math.Clamp(acc[side * hidden + i], 0, 256), other = Math.Clamp(acc[(1 - side) * hidden + i], 0, 256);
            mg += (long)own * output[i] + (long)other * output[i + hidden];
            eg += (long)own * output[i + 2 * hidden] + (long)other * output[i + 3 * hidden];
        }
        phase = Math.Clamp(phase, 0, 24);
        return (lin[0] - lin[1]) / 2 + (int)((mg * phase + eg * (24 - phase)) * (side == 0 ? 1 : -1) / (24 * 65536));
    }
    Span<Move> moves = stackalloc Move[256];
    foreach (bool hybrid in new[] { false, true })
    {
        var model = new NeuralNetwork(hidden, linear, bias, weights, output, classicalBase: hybrid, kingContext: true, turnOutput: true, phaseOutput: true);
        void Check(Board b)
        {
            int phase = b.Squares.Where(p => p >= 0).Sum(p => new[] { 0, 1, 1, 2, 4, 0 }[p % 6]);
            Equal(phase, b.Phase);
            // Reuse unchanged accumulators at different phases/turns to catch
            // cache keys that only include side-to-move or dirty features.
            foreach (int testPhase in new[] { 24, 0, 12, 7, 99, -1, phase })
                for (int side = 0; side < 2; side++) Equal(Reference(b, side, testPhase), b.Neural!.WhiteScoreForSide(side, testPhase));
            int white = Reference(b, b.Side, phase);
            Equal(white, model.EvaluateFromScratch(b));
            int expected = hybrid ? Evaluation.EvaluateClassical(b) + (b.Side == 0 ? 1 : -1) * Math.Clamp(white, -250, 250)
                : (b.Side == 0 ? white : -white) + 12;
#if ASTER_KPK || ASTER_CONVERSION
            if (KpkBitbase.TryEvaluate(b, out int exact)) expected = exact;
#endif
#if ASTER_CONVERSION
            if (MajorMateBitbase.TryEvaluate(b, out int major)) expected = major;
#endif
            Equal(Math.Clamp(expected, -28000, 28000), Evaluation.Evaluate(b));
        }
        foreach (string fen in positions.Select(p => p.Fen).Append("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
            .Append("7k/P7/8/8/8/8/8/7K w - - 0 1"))
        {
            var b = new Board(fen, model); Check(b); ulong key = b.Key;
            int count = b.GenerateLegal(moves);
            for (int i = 0; i < count; i++)
            {
                Require(b.TryMakeMove(moves[i]), "Generated illegal move"); Check(b); Check(b.Clone());
                b.UnmakeMove(); Check(b);
            }
            for (int ply = 0; ply < 60; ply++)
            {
                b.MakeNullMove(); Check(b); b.UnmakeMove(); Check(b);
                int countNow = b.GenerateLegal(moves); if (countNow == 0) break;
                Require(b.TryMakeMove(moves[rng.Next(countNow)]), "Generated illegal move"); Check(b);
            }
            while (b.Ply > 0) { b.UnmakeMove(); Check(b); }
            Equal(fen, b.ToFen()); Equal(key, b.Key);
            _ = Find(b, limits: new SearchLimits(Nodes: 5000)); Check(b); Equal(fen, b.ToFen()); Equal(key, b.Key);
            using var canceled = new CancellationTokenSource(); canceled.Cancel();
            _ = Find(b, cancellation: canceled.Token); Check(b); Equal(fen, b.ToFen()); Equal(key, b.Key);
            b.LoadFen(Board.StartFen); Check(b);
        }
        string path = Path.GetTempFileName();
        try
        {
            model.Save(path); var loaded = NeuralNetwork.Load(path);
            Require(loaded.HasPhaseOutput && loaded.HasTurnOutput && loaded.HasKingContext && !loaded.HasSquaredActivation, "Phase flags lost");
            Equal(hybrid, loaded.ClassicalBase);
            foreach (string fen in positions.Select(p => p.Fen)) Equal(model.EvaluateFromScratch(new Board(fen)), loaded.EvaluateFromScratch(new Board(fen)));
            byte[] original = File.ReadAllBytes(path);
            foreach (byte[] invalid in new[] { original[..^2], original.Concat(new byte[2]).ToArray() })
            {
                File.WriteAllBytes(path, invalid);
                try { NeuralNetwork.Load(path); throw new Exception("Incorrect phase payload accepted"); } catch (FormatException) { }
            }
            File.WriteAllBytes(path, original);
            using (var file = File.OpenWrite(path)) { file.Position = 8; using var writer = new BinaryWriter(file); writer.Write(11); }
            try { NeuralNetwork.Load(path); throw new Exception("Unknown phase format accepted"); } catch (FormatException) { }
        }
        finally { File.Delete(path); }
    }
});
Test("phase output blends signed-int16 extremes in int64 and rejects incompatible flags", () =>
{
    foreach (int hidden in new[] { 8, 256 })
    {
        short[] bias = Enumerable.Repeat((short)256, hidden).ToArray(), weights = new short[768 * 17 * hidden];
        short[] output = Enumerable.Repeat(short.MinValue, hidden * 2).Concat(Enumerable.Repeat(short.MaxValue, hidden * 2)).ToArray();
        var model = new NeuralNetwork(hidden, new short[768 * 17], bias, weights, output, kingContext: true, turnOutput: true, phaseOutput: true);
        var b = new Board(network: model);
        for (int phase = 0; phase <= 24; phase++)
        {
            long mg = (long)hidden * 512 * short.MinValue, eg = (long)hidden * 512 * short.MaxValue;
            int score = (int)((mg * phase + eg * (24 - phase)) / (24 * 65536));
            Equal(score, b.Neural!.WhiteScoreForSide(0, phase)); Equal(-score, b.Neural.WhiteScoreForSide(1, phase));
        }
        Equal(-hidden * 256, model.EvaluateFromScratch(b));
        foreach (bool squared in new[] { false, true })
            try
            {
                _ = new NeuralNetwork(hidden, new short[768 * 17], bias, weights, output, kingContext: true, turnOutput: squared, squaredActivation: squared, phaseOutput: true);
                throw new Exception("Incompatible phase flags accepted");
            }
            catch (ArgumentException) { }
    }
});
Test("squared activation represents interactions inside the unclipped range", () =>
{
    const int hidden = 8;
    var weights = new short[768 * 17 * hidden];
    weights[8 * hidden] = weights[9 * hidden] = 64;
    var output = new short[hidden * 2]; output[0] = 25600;
    foreach (bool squared in new[] { false, true })
    {
        var model = new NeuralNetwork(hidden, new short[768 * 17], Enumerable.Repeat((short)64, hidden).ToArray(),
            weights, output, kingContext: true, turnOutput: true, squaredActivation: squared);
        int[] scores = new[] { "8", "P7", "1P6", "PP6" }.Select(rank =>
            model.EvaluateFromScratch(new Board($"7k/8/8/8/8/8/{rank}/7K w - - 0 1"))).ToArray();
        Equal(squared ? 6 : 25, scores[0]); Equal(squared ? 25 : 50, scores[1]);
        Equal(scores[1], scores[2]); Equal(squared ? 56 : 75, scores[3]);
        Equal(squared ? 12 : 0, scores[3] - scores[1] - scores[2] + scores[0]);
    }
});
Test("neural output accumulation preserves signed-int16 extremes", () =>
{
    foreach (int hidden in new[] { 8, 256 })
    {
        var weights = new short[768 * hidden];
        Array.Fill(weights, (short)256, (6 * 64 + 48) * hidden, hidden);
        var output = Enumerable.Repeat(short.MinValue, hidden).ToArray();
        var model = new NeuralNetwork(hidden, new short[768], new short[hidden], weights, output);
        var board = new Board("7k/8/8/8/8/8/P6P/7K w - - 0 1", model);
        Equal(hidden * 128, board.Neural!.WhiteScore);
        Equal(Math.Min(28000, hidden * 128 + 12), Evaluation.Evaluate(board));
    }
});
Test("neural model serialization and malformed payload rejection", () =>
{
    string path = Path.GetTempFileName();
    try
    {
        short[] linear = new short[768]; for (int i = 0; i < 768; i++) linear[i] = (short)(i - 384);
        var network = new NeuralNetwork(8, linear, new short[8], new short[768 * 8], new short[8]);
        network.Save(path); var restored = NeuralNetwork.Load(path);
        Equal(network.EvaluateFromScratch(new Board()), restored.EvaluateFromScratch(new Board()));
        File.AppendAllText(path, "extra");
        try { NeuralNetwork.Load(path); throw new Exception("Extra payload accepted"); } catch (FormatException) { }
        File.WriteAllBytes(path, "invalid!"u8.ToArray());
        try { NeuralNetwork.Load(path); throw new Exception("Bad magic accepted"); } catch (FormatException) { }
    }
    finally { File.Delete(path); }
});
Test("neural search preserves state and changing evaluator does not change hash", () =>
{
    short[] linear = new short[768];
    for (int p = 0; p < 12; p++) for (int s = 0; s < 64; s++)
        linear[p * 64 + s] = (short)((p < 6 ? 1 : -1) * (p % 6 == 5 ? 0 : Evaluation.Material[p % 6]));
    var model = new NeuralNetwork(8, linear, new short[8], new short[768 * 8], new short[8]);
    var board = new Board("4k3/8/8/8/3q4/2P5/8/4K3 w - - 0 1");
    ulong key = board.Key; board.SetNetwork(model); Equal(key, board.Key);
    string fen = board.ToFen(); int eval = board.Neural!.WhiteScore;
    Equal("c3d4", Find(board).BestMove.ToString()); Equal(fen, board.ToFen()); Equal(eval, board.Neural.WhiteScore);
    board.SetNetwork(null); Equal(key, board.Key); Require(board.Neural == null, "Neural evaluator did not detach");
});
Test("hybrid evaluation retains classical score and bounds learned correction", () =>
{
    short[] linear = new short[768];
    for (int p = 0; p < 12; p++) for (int s = 0; s < 64; s++) linear[p * 64 + s] = (short)(p < 6 ? 1000 : -1000);
    var model = new NeuralNetwork(8, linear, new short[8], new short[768 * 8], new short[8], classicalBase: true);
    foreach (string side in new[] { "w", "b" })
    {
        var board = new Board($"4k3/8/8/8/8/8/P6P/4K3 {side} - - 0 1", model);
        int classical = Evaluation.EvaluateClassical(board);
        Equal(classical + (side == "w" ? 250 : -250), Evaluation.Evaluate(board));
    }
    string path = Path.GetTempFileName();
    try { model.Save(path); Require(NeuralNetwork.Load(path).ClassicalBase, "Hybrid version did not round trip"); }
    finally { File.Delete(path); }
});
Test("KPK recognizes rook-pawn draws, captures and safe underpromotion", () =>
{
    foreach (var (fen, won) in new (string, bool)[]
    {
        ("k7/P7/K7/8/8/8/8/8 w - - 0 1", false),
        ("k7/P7/K7/8/8/8/8/8 b - - 0 1", false),
        ("8/8/8/8/8/k7/P7/7K b - - 0 1", false),
        ("8/5P1k/5K2/8/8/8/8/8 w - - 0 1", true),
        ("7k/8/8/8/8/8/P7/7K w - - 0 1", true)
    })
    {
        var b = new Board(fen); ulong key = b.Key;
        Require(KpkBitbase.Probe(b, out bool actual, out int bound), "KPK unsupported");
        Equal(won, actual); Require(bound is >= 0 and <= 38, "Invalid conversion bound");
        Equal(fen, b.ToFen()); Equal(key, b.Key);
    }
    Require(!KpkBitbase.Probe(new Board(), out _, out _), "Full material treated as KPK");
    var stale = new Board("k7/P7/K7/8/8/8/8/8 b - - 100 1");
    Equal(0, Find(stale).Score); Equal(Move.None, Find(stale).BestMove);
});
Test("KPK normalization respects pawn color, file reflection and reversible clock", () =>
{
    const string fen = "7k/8/8/8/8/8/P7/7K w - - 0 1";
    var original = new Board(fen);
    Require(KpkBitbase.Probe(original, out bool won, out int bound) && won, "Expected win");
    var reflected = new Board("k7/8/8/8/8/8/7P/K7 w - - 0 1");
    var reversed = new Board("7k/p7/8/8/8/8/8/7K b - - 0 1");
    foreach (Board b in new[] { reflected, reversed })
    {
        Require(KpkBitbase.Probe(b, out bool result, out int distance), "Normalized KPK unsupported");
        Equal(won, result); Equal(bound, distance);
    }
    Require(KpkBitbase.TryEvaluate(original, out int value) && value > 0, "Winning pawn not valued");
    var late = new Board(fen.Replace("0 1", "99 1"));
    Require(!KpkBitbase.TryEvaluate(late, out _), "Rule50 uncertainty must fall back");
    Require(KpkBitbase.TryEvaluate(new Board("k7/P7/K7/8/8/8/8/8 w - - 99 1"), out int draw) && draw == 0,
        "Rule50 cannot turn a theoretical draw into a win");
});
#if ASTER_KPK || ASTER_CONVERSION
Test("KPK knowledge overrides neural estimates while preserving accumulators", () =>
{
    var linear = new short[768];
    Array.Fill(linear, short.MinValue, 0, 64);
    var model = new NeuralNetwork(8, linear, new short[8], new short[768 * 8], new short[8]);
    var win = new Board("7k/8/8/8/8/8/P7/7K w - - 0 1", model);
    int raw = win.Neural!.WhiteScore;
    Require(raw < -10000 && Evaluation.Evaluate(win) > 0, "Exact knowledge lost to neural estimate");
    Equal(raw, win.Neural.WhiteScore);
    var draw = new Board("k7/P7/K7/8/8/8/8/8 w - - 0 1", model);
    Equal(0, Evaluation.Evaluate(draw));
    var key = win.Key; string fen = win.ToFen();
    _ = Find(win, limits: new SearchLimits(Nodes: 5000));
    Equal(key, win.Key); Equal(fen, win.ToFen()); Equal(raw, win.Neural.WhiteScore);
});
#endif
Test("major-piece mate tables distinguish mate, capture and stalemate", () =>
{
    foreach (string fen in new[] { "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1", "7k/5K2/8/8/8/8/8/7R b - - 0 1" })
    {
        Require(MajorMateBitbase.Probe(new Board(fen), out int strong, out bool won, out int distance), "Unsupported major mate");
        Equal(0, strong); Require(won, "Mate must be won"); Equal(0, distance);
    }
    foreach (string fen in new[] { "7k/6Q1/8/8/8/8/8/K7 b - - 0 1", "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1" })
    {
        Require(MajorMateBitbase.Probe(new Board(fen), out _, out bool won, out _), "Unsupported major draw");
        Require(!won, "Capture/stalemate cannot be won");
    }
});
Test("general mate certificates cover every defense, terminal leaf and special move", () =>
{
    var cases = new (string Fen, int Bound)[]
    {
        ("6k1/5ppp/8/8/8/8/5PPP/3Q2K1 w - - 0 1", 1),
        ("7k/7p/4K1Q1/8/8/8/8/8 w - - 0 1", 5),
        ("k7/p1P5/2K5/8/8/8/8/8 w - - 0 1", 1),
        ("5B2/7B/6P1/R4pPk/8/7K/8/8 w - f6 0 1", 1),
        ("5k2/4p1p1/8/3B3B/8/8/8/4K2R w K - 0 1", 1)
    };
    foreach (var test in cases)
    {
        var b = new Board(test.Fen); ulong key = b.Key; int score = Evaluation.Evaluate(b);
        MateStrategyProof proof = MateProof.Build(b, b.Side, test.Bound);
        Require(proof.Complete, proof.Summary); Equal(test.Bound, proof.RootDistance);
        Equal(test.Fen, b.ToFen()); Equal(key, b.Key); Equal(score, Evaluation.Evaluate(b));
        var seen = new HashSet<int>();
        void Check(int id, Board current)
        {
            Require(seen.Add(id), "Repeated certificate node");
            ProofNode node = proof.Nodes[id]; Equal(current.ToFen(), node.Fen);
            Span<Move> moves = stackalloc Move[256]; int count = current.GenerateLegal(moves);
            if (count == 0)
            {
                Require(current.InCheck && current.Side != proof.StrongSide, "False mate leaf");
                Equal(0, node.Distance); Equal(0, node.Edges.Count); return;
            }
            Require(!current.InsufficientMaterial() && !current.IsRepetition() && current.HalfmoveClock < 100, "Draw in winning certificate");
            Equal(current.Side == proof.StrongSide ? 1 : count, node.Edges.Count);
            foreach (ProofEdge edge in node.Edges)
            {
                Require(current.TryMakeMove(current.ParseMove(edge.Move)), "Illegal proof edge");
                try { Require(proof.Nodes[edge.To].Distance < node.Distance, "Nondecreasing bound"); Check(edge.To, current); }
                finally { current.UnmakeMove(); }
            }
            Equal(node.Fen, current.ToFen());
        }
        Check(0, new Board(test.Fen)); Equal(proof.Nodes.Count, seen.Count);
        Require(proof.Nodes.Count <= proof.Visits && proof.Visits <= proof.NodeLimit, "Budget exceeded");
        if (test.Bound == 5)
        {
            Require(!MateProof.Build(b, b.Side, 3).Complete, "Mate claimed outside horizon");
            Play(b, proof.Nodes[0].Edges[0].Move);
            var defender = new Board(b.ToFen());
            MateStrategyProof defense = MateProof.Build(defender, proof.StrongSide, 4);
            Require(defense.Complete && defense.RootDistance == 4, "Defender-root proof failed");
            Equal(defender.GenerateLegal(new Move[256]), defense.Nodes[0].Edges.Count);
            b.UnmakeMove(); Equal(test.Fen, b.ToFen());
        }
    }
});
Test("general mate proof refuses incomplete, drawn, unsafe or cancelled guarantees", () =>
{
    var b = new Board(); ulong key = b.Key;
    MateStrategyProof limited = MateProof.Build(b, 0, 7, 1);
    Equal("node_limit", limited.Reason); Require(!limited.Complete && limited.Nodes.Count == 0 && limited.Visits == 1, "Partial guarantee escaped");
    using var canceled = new CancellationTokenSource(); canceled.Cancel();
    var result = MateProof.Build(b, 0, cancellation: canceled.Token);
    Equal("cancelled", result.Reason); Require(!result.Complete && result.Nodes.Count == 0, "Cancelled guarantee escaped");
    Equal(Board.StartFen, b.ToFen()); Equal(key, b.Key);
    var history = new Board(); Play(history, "g1f3", "g8f6"); Equal("prior_history", MateProof.Build(history, 0).Reason);
    Play(history, "e2e4"); Require(MateProof.Build(history, 1, 0).Reason != "prior_history", "Reset clock rejected");
    foreach (string fen in new[] { "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", "7k/8/8/8/8/8/8/K7 w - - 0 1" })
        Require(!MateProof.Build(new Board(fen), 0, 3).Complete, "Draw certified as mate");
    string mate = "7k/6Q1/6K1/8/8/8/8/8 b - - 100 1";
    Require(MateProof.Build(new Board(mate), 0, 0, 1).Complete, "Rule50 overrode existing mate");
    Require(!MateProof.Build(new Board(mate), 1, 0).Complete, "Mated side assigned the win");
    Equal("rule50_boundary", MateProof.Build(new Board("6k1/5ppp/8/8/8/8/5PPP/3Q2K1 w - - 99 1"), 0, 1).Reason);
    Equal("invalid_position", MateProof.Build(new Board("7k/5KP1/8/8/8/8/8/8 w - - 0 1"), 0).Reason);
    Equal("invalid_position", MateProof.Build(new Board("4k3/8/8/8/8/8/8/4K3 w K - 0 1"), 0).Reason);
    Equal("invalid_position", MateProof.Build(new Board("4r2k/8/8/8/1b6/5n2/8/4K3 w - - 0 1"), 1).Reason);
    foreach (int bound in new[] { -1, 8 })
        try { MateProof.Build(b, 0, bound); throw new Exception("Invalid bound accepted"); } catch (ArgumentOutOfRangeException) { }
    foreach (int budget in new[] { 0, 100001 })
        try { MateProof.Build(b, 0, nodeLimit: budget); throw new Exception("Invalid budget accepted"); } catch (ArgumentOutOfRangeException) { }
});
Test("strategy proof covers every defense, respects limits and leaves the board intact", () =>
{
    var board = new Board("7k/8/5K2/8/1R6/8/8/8 w - - 0 1");
    string fen = board.ToFen(); ulong key = board.Key;
    StrategyProof proof = EndgameProof.Build(board);
    Require(proof.Complete && proof.Nodes.Count > 1, "No complete mating proof");
    Span<Move> legal = stackalloc Move[256];
    foreach (ProofNode node in proof.Nodes)
    {
        var replay = new Board(node.Fen); int count = replay.GenerateLegal(legal);
        if (count == 0) { Require(replay.InCheck && node.Distance == 0, "Non-mating proof leaf"); continue; }
        Equal(replay.Side == proof.StrongSide ? 1 : count, node.Edges.Count);
        foreach (ProofEdge edge in node.Edges) Require(proof.Nodes[edge.To].Distance < node.Distance, "Nondecreasing proof edge");
    }
    Equal(fen, board.ToFen()); Equal(key, board.Key);
    Require(!EndgameProof.Build(board, 1).Complete, "A truncated strategy was labeled complete");
    Equal(fen, board.ToFen()); Equal(key, board.Key);
});
Test("strategy proof declines arbitrary played history and uncertain rule50", () =>
{
    var board = new Board("7k/8/8/8/8/8/Q7/K7 w - - 0 1"); Play(board, "a2b2");
    Equal("prior_history", EndgameProof.Build(board).Reason);
    Equal("rule50_boundary", EndgameProof.Build(new Board("7k/8/8/8/8/8/Q7/K7 w - - 99 1")).Reason);
    Equal("theoretical_draw", EndgameProof.Build(new Board("7k/6Q1/8/8/8/8/8/K7 b - - 0 1")).Reason);
});
Test("major conversion policy respects requested moves, history and clock", () =>
{
    var board = new Board("7k/8/8/8/8/8/Q7/K7 w - - 0 1"); string fen = board.ToFen(); ulong key = board.Key;
    Span<Move> legal = stackalloc Move[256]; int count = board.GenerateLegal(legal);
    Require(MajorMateBitbase.TryRestrictRoot(board, legal[..count], null, out Move[] moves) && moves.Length > 0, "No decreasing mate strategy");
    Equal(fen, board.ToFen()); Equal(key, board.Key);
    Require(MajorMateBitbase.TryRestrictRoot(board, legal[..count], [moves[0]], out Move[] requested), "Requested strategy lost");
    Equal(1, requested.Length); Equal(moves[0], requested[0]);
    Require(!MajorMateBitbase.TryRestrictRoot(board, legal[..count], [], out _), "Empty searchmoves ignored");
    var late = new Board(fen.Replace("0 1", "99 1"));
    Require(!MajorMateBitbase.TryEvaluate(late, out _), "Rule50 uncertainty ignored");
    Require(!MajorMateBitbase.TryRestrictRoot(late, legal[..count], null, out _), "Late clock cannot force strategy");
    var cycle = new Board("7k/8/8/8/8/8/Q7/K7 w - - 0 1");
    for (int i = 0; i < 2; i++) foreach (string move in new[] { "a2b2", "h8g8", "b2a2", "g8h8" }) Play(cycle, move);
    count = cycle.GenerateLegal(legal);
    Require(cycle.IsRepetition(), "Expected game-history repetition");
    Require(!MajorMateBitbase.TryRestrictRoot(cycle, legal[..count], null, out _), "Repetition overruled");
});
#if ASTER_CONVERSION
Test("major conversion overrides neural output and reduces root mate distance", () =>
{
    var linear = new short[768]; Array.Fill(linear, short.MinValue, 4 * 64, 64);
    var model = new NeuralNetwork(8, linear, new short[8], new short[768 * 8], new short[8]);
    var board = new Board("7k/8/8/8/8/8/Q7/K7 w - - 0 1", model);
    int raw = board.Neural!.WhiteScore;
    Require(raw < -10000 && Evaluation.Evaluate(board) > 0, "Mate knowledge lost to network");
    Require(MajorMateBitbase.Probe(board, out _, out bool won, out int distance) && won, "Expected win");
    string fen = board.ToFen(); SearchResult result = Find(board, limits: new SearchLimits(Nodes: 100));
    Equal(fen, board.ToFen()); Equal(raw, board.Neural.WhiteScore);
    Require(board.TryMakeMove(result.BestMove), "Illegal strategy move");
    try { Require(MajorMateBitbase.Probe(board, out _, out bool childWon, out int childDistance) && childWon && childDistance < distance, "Mate distance did not decrease"); }
    finally { board.UnmakeMove(); }
    Equal(fen, board.ToFen()); Equal(raw, board.Neural.WhiteScore);
});
#endif
Test("quiescence recognizes a stalemating queen promotion and selects rook", () =>
{
    var board = new Board("8/5P1k/5K2/8/8/8/8/8 w - - 0 1");
    Move[] promotions = [board.ParseMove("f7f8n"), board.ParseMove("f7f8b"), board.ParseMove("f7f8r"), board.ParseMove("f7f8q")];
    SearchResult result = Find(board, limits: new SearchLimits(Depth: 1, SearchMoves: promotions));
    Equal("f7f8r", result.BestMove.ToString()); Require(result.Score > 0, "Winning underpromotion not valued");
    Play(board, "f7f8q"); Require(!board.InCheck, "Expected stalemate, not mate");
    Span<Move> legal = stackalloc Move[256]; Equal(0, board.GenerateLegal(legal));
});
Test("checkmate at the quiescence horizon beats a new rule-50 claim", () =>
{
    var board = new Board("6k1/5ppp/8/8/8/8/5PPP/3Q2K1 w - - 99 1");
    Move mate = board.ParseMove("d1d8");
    SearchResult result = Find(board, limits: new SearchLimits(Depth: 1, SearchMoves: [mate]));
    Equal(mate, result.BestMove); Equal(Search.Mate - 1, result.Score);
});

Test("quiescence terminal rules hold at the maximum-ply boundary", () =>
{
    // Valid ordinary games rarely reach this safety boundary. Invoke the
    // actual horizon routine after initializing its usual search state.
    const System.Reflection.BindingFlags flags = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic;
    int Horizon(Board b, int ply)
    {
        var search = new Search(new TranspositionTable(1));
        _ = search.Run(b, new SearchLimits(Nodes: 1));
        typeof(Search).GetField("limits", flags)!.SetValue(search, new SearchLimits(Nodes: 10000));
        typeof(Search).GetField("nodes", flags)!.SetValue(search, 0L);
        return (int)typeof(Search).GetMethod("Quiescence", flags)!.Invoke(search, [ply, -32000, 32000])!;
    }
    foreach (int ply in new[] { Search.MaxPly - 2, Search.MaxPly - 1 })
    {
        foreach (int clock in new[] { 0, 100 })
        {
            var mate = new Board($"7k/6Q1/6K1/8/8/8/8/8 b - - {clock} 1");
            string fen = mate.ToFen(); ulong key = mate.Key;
            Equal(-Search.Mate + ply, Horizon(mate, ply)); Equal(fen, mate.ToFen()); Equal(key, mate.Key);
            var stalemate = new Board($"7k/5Q2/6K1/8/8/8/8/8 b - - {clock} 1");
            Equal(0, Horizon(stalemate, ply));
        }
    }
    var checkedBoard = new Board("7k/7Q/8/8/8/8/8/K7 b - - 0 1");
    Equal(Evaluation.Evaluate(checkedBoard), Horizon(checkedBoard, Search.MaxPly - 1));
    Equal(0, Horizon(checkedBoard, Search.MaxPly - 2)); // Legal king capture draws.
});
Test("a stopped quiescence evasion always restores its root", () =>
{
    const System.Reflection.BindingFlags flags = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic;
    var b = new Board("3Q3k/8/8/8/8/8/8/K7 b - - 0 1");
    string fen = b.ToFen(); ulong key = b.Key; int evaluation = Evaluation.Evaluate(b);
    var search = new Search(new TranspositionTable(1));
    _ = search.Run(b, new SearchLimits(Nodes: 1));
    typeof(Search).GetField("limits", flags)!.SetValue(search, new SearchLimits(Nodes: 2));
    typeof(Search).GetField("nodes", flags)!.SetValue(search, 0L);
    bool stopped = false;
    try { _ = typeof(Search).GetMethod("Quiescence", flags)!.Invoke(search, [4, -32000, 32000]); }
    catch (System.Reflection.TargetInvocationException error) when (error.InnerException?.GetType().Name == "SearchStoppedException") { stopped = true; }
    Require(stopped, "Expected a stop while searching a checked root's evasions");
    Equal(fen, b.ToFen()); Equal(key, b.Key); Equal(evaluation, Evaluation.Evaluate(b));
    Equal(new Board(fen).Key, b.Key);
});

#if ASTER_IIR
Test("unseeded secondary search stores only its actual depth and preserves guarded nodes", () =>
{
    const System.Reflection.BindingFlags flags = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic;
    void CheckDepth(Board board, int ply, int alpha, int beta, bool seedMove, int expected)
    {
        string fen = board.ToFen(); ulong key = board.Key; int evaluation = Evaluation.Evaluate(board);
        var table = new TranspositionTable(1); var search = new Search(table);
        _ = search.Run(board, new SearchLimits(Nodes: 1));
        table.Clear();
        if (seedMove) table.Store(board.SearchKey, board.ParseMove("e2e4"), 0, 0, Bound.Upper, ply);
        typeof(Search).GetField("limits", flags)!.SetValue(search, new SearchLimits(Nodes: 500000));
        typeof(Search).GetField("nodes", flags)!.SetValue(search, 0L);
        _ = typeof(Search).GetMethod("Negamax", flags)!.Invoke(search, [5, ply, alpha, beta, true]);
        Require(table.Probe(board.SearchKey, ply, out _, out _, out int depth, out _), "No completed node bound");
        Equal(expected, depth);
        Equal(fen, board.ToFen()); Equal(key, board.Key); Equal(evaluation, Evaluation.Evaluate(board));
    }
    CheckDepth(new Board(), 1, 5000, 5001, false, 4);
    CheckDepth(new Board(), 1, 5000, 5001, true, 5);
    CheckDepth(new Board(), 0, 5000, 5001, false, 5);
    CheckDepth(new Board(), 1, -1000, 1000, false, 5);
    CheckDepth(new Board(Board.StartFen.Replace("0 1", "90 1")), 1, 5000, 5001, false, 5);
    CheckDepth(new Board("8/7k/8/8/8/8/P7/K7 w - - 0 1"), 1, 5000, 5001, false, 5);
});
#endif

Console.WriteLine($"\n{passed} passed, {failed} failed.");
return failed == 0 ? 0 : 1;
