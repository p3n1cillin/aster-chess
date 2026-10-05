using System.Diagnostics;
using System.Text.Json;
using Aster;
using Aster.Play;

int passed = 0, failed = 0;
void Check(bool condition, string message) { if (!condition) throw new Exception(message); }
async Task Test(string name, Func<Task> action)
{
    try { await action(); passed++; Console.WriteLine("PASS " + name); }
    catch (Exception error) { failed++; Console.WriteLine($"FAIL {name}: {error}"); }
}
async Task<PositionView> Idle(Game game)
{
    var timer = Stopwatch.StartNew();
    while (game.Snapshot().Thinking && timer.ElapsedMilliseconds < 6000) await Task.Delay(10);
    var state = game.Snapshot(); Check(!state.Thinking && state.Error == null, "Search did not finish successfully"); return state;
}
async Task Reject(Func<Task> action)
{
    try { await action(); } catch (Exception e) when (e is ArgumentException or FormatException or InvalidOperationException) { return; }
    throw new Exception("Invalid command was accepted");
}

await Test("human move, native reply, real search events and paired takeback", async () =>
{
    var game = new Game(); var stream = game.Subscribe();
    await game.NewAsync(new(Milliseconds: 300));
    await game.MoveAsync("e2e4"); var state = await Idle(game);
    Check(state.Moves.Length == 2 && state.Side == 0 && state.Moves[0].San == "e4", "Missing reply");
    var board = new Board(); foreach (var move in state.Moves) Check(board.TryMakeMove(board.ParseMove(move.Uci)), "Illegal game move");
    Check(board.ToFen() == state.Fen && state.Depths.Length > 0 && state.Trace?.View.Finished == true, "Missing completed visualization");
    long previous = 0; bool analysis = false, trace = false;
    while (stream.Reader.TryRead(out var message))
    {
        Check(message.Sequence > previous, "Events arrived out of order"); previous = message.Sequence;
        using var json = JsonDocument.Parse(message.Json);
        analysis |= message.Kind == "analysis"; trace |= message.Kind == "trace";
    }
    Check(analysis && trace && state.Revision >= previous, "Missing event stream");
    Check(game.Pgn().Contains("1. e4 ") && game.Pgn().Contains("[White \"You\"]"), "Incorrect PGN");
    state = await game.UndoAsync(); Check(state.Fen == Board.StartFen && state.Moves.Length == 0 && !state.Thinking, "Takeback failed");
    game.Unsubscribe(stream);
});
await Test("playing Black and taking back retains Aster's opening", async () =>
{
    var game = new Game(); await game.NewAsync(new("black", 300)); var state = await Idle(game);
    Check(state.HumanSide == 1 && state.Side == 1 && state.Moves.Length == 1, "Aster did not open as White");
    string opening = state.Fen; await game.MoveAsync(state.Legal[0]); await Idle(game);
    state = await game.UndoAsync(); Check(state.Fen == opening && state.Moves.Length == 1, "Wrong Black takeback");
});
await Test("analysis and stop preserve the live game position", async () =>
{
    var game = new Game(); await game.NewAsync(new(Milliseconds: 1000)); await game.AnalyzeAsync();
    await Task.Delay(90); var state = await game.StopAsync();
    Check(state.Fen == Board.StartFen && state.Moves.Length == 0 && state.Mode == "analyze" && !state.Thinking, "Analysis played a move");
    Check(state.Trace?.View.Finished == true && state.Depths.Length > 0, "Stopped search lacked visualization");
});
await Test("move now chooses a legal reply and undo cancels an unfinished search", async () =>
{
    var game = new Game(); await game.NewAsync(new(Milliseconds: 3000)); await game.MoveAsync("d2d4");
    var state = await game.StopAsync(); Check(state.Moves.Length == 2 && !state.Thinking, "Stop did not play best available move");
    await game.UndoAsync(); await game.MoveAsync("e2e4"); state = await game.UndoAsync();
    await Task.Delay(50); Check(state.Fen == Board.StartFen && game.Snapshot().Moves.Length == 0, "Cancelled worker changed the board");
});
await Test("new game discards an old worker's reply", async () =>
{
    var game = new Game(); await game.NewAsync(new(Milliseconds: 3000)); await game.MoveAsync("e2e4");
    var state = await game.NewAsync(new(Milliseconds: 300)); await Task.Delay(50);
    Check(!state.Thinking && game.Snapshot().Fen == Board.StartFen && game.Snapshot().Moves.Length == 0, "Old worker leaked into new game");
});
await Test("invalid moves, side, budget and FEN preserve the existing game", async () =>
{
    var game = new Game(); string fen = game.Snapshot().Fen;
    await Reject(async () => await game.MoveAsync("e2e5"));
    await Reject(async () => await game.NewAsync(new("purple")));
    await Reject(async () => await game.NewAsync(new(Milliseconds: 1)));
    await Reject(async () => await game.NewAsync(new(Fen: "bad")));
    await Reject(async () => await game.NewAsync(new(Fen: "4k3/8/8/8/8/8/4R3/4K3 w - - 0 1")));
    Check(game.Snapshot().Fen == fen && game.Snapshot().Moves.Length == 0, "Rejected request changed game");
});
await Test("checkmate, stalemate, insufficient material and fifty-move terminals", async () =>
{
    foreach (var (fen, result) in new[] {
        ("7k/6Q1/6K1/8/8/8/8/8 b - - 100 1", "1-0"),
        ("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", "1/2-1/2"),
        ("7k/8/6K1/8/8/8/8/8 w - - 0 1", "1/2-1/2"),
        ("7k/8/6K1/8/8/8/R7/8 w - - 100 1", "1/2-1/2") })
    {
        var game = new Game(); var state = await game.NewAsync(new(Fen: fen));
        Check(state.Result == result && !state.Thinking && state.Legal.Length == 0, "Incorrect terminal outcome");
        await Reject(async () => await game.AnalyzeAsync());
    }
});
await Test("native SAN handles castling, en passant, promotion and disambiguation", () =>
{
    foreach (var (fen, move, san) in new[] {
        ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "e1g1", "O-O"),
        ("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1", "e5d6", "exd6"),
        ("4k3/P7/8/8/8/8/8/4K3 w - - 0 1", "a7a8n", "a8=N"),
        ("4k3/8/8/8/8/8/8/1N2KN2 w - - 0 1", "b1d2", "Nbd2"),
        ("7k/8/5KQ1/8/8/8/8/8 w - - 0 1", "g6g7", "Qg7#") })
    {
        var board = new Board(fen); var hash = board.Key;
        Check(ChessNotation.San(board, board.ParseMove(move)) == san, "Wrong SAN for " + move);
        Check(board.ToFen() == fen && board.Key == hash, "Notation corrupted board");
    }
    return Task.CompletedTask;
});
await Test("promotion choices and custom-position PGN retain native history", async () =>
{
    const string fen = "4k3/P7/8/8/8/8/8/4K3 w - - 0 1";
    var game = new Game(); var state = await game.NewAsync(new(Milliseconds: 300, Fen: fen));
    Check(state.Legal.Count(move => move.StartsWith("a7a8")) == 4, "Promotion choices missing");
    await game.MoveAsync("a7a8n"); state = await Idle(game);
    Check(state.Moves[0].San == "a8=N" && state.Result == "1/2-1/2", "Underpromotion game not terminal");
    Check(game.Pgn().Contains("[SetUp \"1\"]") && game.Pgn().Contains(fen), "Custom origin missing from PGN");
});
await Test("PV notation and geometric attack maps preserve the root", () =>
{
    var board = new Board(); var variation = ChessNotation.Variation(board, [board.ParseMove("e2e4")]);
    Check(variation.Length == 1 && variation[0].San == "e4" && board.ToFen() == Board.StartFen, "PV changed root");
    var state = new Game().Snapshot();
    Check(state.WhiteAttacks.Length == 64 && state.BlackAttacks.Length == 64, "Wrong attack-map shape");
    Check(state.WhiteAttacks[20] == 2 && state.BlackAttacks[44] == 2, "Wrong e3/e6 attack count");
    Check(state.ScoreWhite == state.PieceSquareWhite + state.StructureActivityWhite + state.TempoWhite, "Evaluation terms don't sum");
    return Task.CompletedTask;
});
Console.WriteLine($"\n{passed} passed, {failed} failed.");
return failed == 0 ? 0 : 1;
