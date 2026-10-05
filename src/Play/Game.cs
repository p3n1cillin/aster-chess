using System.Numerics;
using System.Text;
using System.Text.Json;
using System.Threading.Channels;
using Aster;

namespace Aster.Play;

public sealed record NewGame(string Side = "white", int Milliseconds = 3000, string? Fen = null);
public sealed record PlayMove(string Move);
public sealed record Settings(int Milliseconds);
public sealed record PlayedMove(string Uci, string San, string Fen, int Side, int Number);
public sealed record VariationMove(string Uci, string San, string Fen);
public sealed record AnalysisView(Guid SearchId, string RootFen, int RootSide, int Depth, int SelectiveDepth,
    int ScoreWhite, long Nodes, long Milliseconds, int HashFull, VariationMove[] Pv);
public sealed record TraceView(Guid SearchId, string RootFen, int RootSide, SearchView View);
public sealed record EventMessage(long Sequence, string Kind, string Json);
public sealed record PositionView(string Fen, int Side, bool InCheck, int HumanSide, bool Thinking, string Mode,
    string Status, string? Result, int Milliseconds, string[] Legal, PlayedMove[] Moves, int ScoreWhite,
    int MaterialWhite, int PieceSquareWhite, int StructureActivityWhite, int TempoWhite, int Phase,
    int[] WhiteAttacks, int[] BlackAttacks, Guid SearchId, AnalysisView[] Depths, TraceView? Trace, string? Error, long Revision);

public sealed class Game
{
    public static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    private readonly object sync = new();
    private readonly SemaphoreSlim commands = new(1, 1);
    private readonly List<Channel<EventMessage>> subscribers = [];
    private readonly List<PlayedMove> moves = [];
    private readonly List<AnalysisView> depths = [];
    private Board board = new();
    private readonly TranspositionTable table = new(64);
    private readonly Search search;
    private CancellationTokenSource? cancellation;
    private Task? running;
    private Guid searchId;
    private TraceView? lastTrace;
    private int humanSide, milliseconds = 3000;
    private bool thinking;
    private string mode = "play", startFen = Board.StartFen;
    private string? error;
    private long sequence;

    public Game() => search = new(table);
    private static void Budget(int value) { if (value is < 300 or > 15000) throw new ArgumentException("Choose 300..15000 milliseconds per reply."); }
    public PositionView Snapshot() { lock (sync) return SnapshotLocked(); }
    private (string Status, string? Result) Outcome()
    {
        if (!board.HasAnyLegalMove()) return board.InCheck
            ? ("Checkmate", board.Side == 0 ? "0-1" : "1-0") : ("Draw by stalemate", "1/2-1/2");
        if (board.InsufficientMaterial()) return ("Draw by insufficient material", "1/2-1/2");
        if (board.IsRepetition()) return ("Draw by threefold repetition", "1/2-1/2");
        if (board.HalfmoveClock >= 100) return ("Draw by fifty-move rule", "1/2-1/2");
        return (board.InCheck ? "Check" : "Playing", null);
    }
    private PositionView SnapshotLocked()
    {
        Span<Move> legal = stackalloc Move[256]; int count = board.GenerateLegal(legal);
        var outcome = Outcome(); int orientation = board.Side == 0 ? 1 : -1;
        int score = Evaluation.Evaluate(board) * orientation;
        int phase = Math.Min(24, board.Phase);
        int pieces = (board.MgScore * phase + board.EgScore * (24 - phase)) / 24;
        int material = 0;
        for (int piece = 0; piece < 12; piece++)
            if (piece % 6 != 5) material += (piece < 6 ? 1 : -1) * BitOperations.PopCount(board.Pieces[piece]) * Evaluation.Material[piece % 6];
        int[][] attacks = [new int[64], new int[64]];
        for (int piece = 0; piece < 12; piece++)
        {
            ulong remaining = board.Pieces[piece];
            while (remaining != 0)
            {
                int square = Attacks.Pop(ref remaining);
                ulong controlled = (piece % 6) switch
                {
                    0 => Attacks.Pawn[piece / 6, square], 1 => Attacks.Knight[square],
                    2 => Attacks.Bishop(square, board.Occupied), 3 => Attacks.Rook(square, board.Occupied),
                    4 => Attacks.Bishop(square, board.Occupied) | Attacks.Rook(square, board.Occupied), _ => Attacks.King[square]
                };
                while (controlled != 0) attacks[piece / 6][Attacks.Pop(ref controlled)]++;
            }
        }
        return new(board.ToFen(), board.Side, board.InCheck, humanSide, thinking, mode, outcome.Status, outcome.Result,
            milliseconds, outcome.Result == null ? legal[..count].ToArray().Select(m => m.ToString()).ToArray() : [],
            moves.ToArray(), score, material, pieces, score - pieces - orientation * 12, orientation * 12, phase,
            attacks[0], attacks[1], searchId, depths.ToArray(), lastTrace, error, sequence);
    }
    private void Publish(string kind, object value)
    {
        sequence++;
        if (value is PositionView state) value = state with { Revision = sequence };
        var message = new EventMessage(sequence, kind, JsonSerializer.Serialize(value, Json));
        foreach (var subscriber in subscribers) subscriber.Writer.TryWrite(message);
    }
    public Channel<EventMessage> Subscribe()
    {
        lock (sync)
        {
            if (subscribers.Count >= 12) throw new InvalidOperationException("Too many open views. Close an unused Aster tab.");
            var channel = Channel.CreateBounded<EventMessage>(new BoundedChannelOptions(128) { FullMode = BoundedChannelFullMode.DropOldest });
            subscribers.Add(channel); return channel;
        }
    }
    public void Unsubscribe(Channel<EventMessage> channel) { lock (sync) { subscribers.Remove(channel); channel.Writer.TryComplete(); } }
    private async Task CancelAndJoin(bool discard)
    {
        Task? pending;
        lock (sync) { if (discard) searchId = Guid.NewGuid(); cancellation?.Cancel(); pending = running; }
        if (pending != null) await pending;
        lock (sync) { thinking = false; running = null; cancellation?.Dispose(); cancellation = null; }
    }
    public void Cancel() { lock (sync) cancellation?.Cancel(); }
    private void Start(bool analyze = false)
    {
        if (Outcome().Result != null || (!analyze && board.Side == humanSide)) return;
        Board root = board.Clone(), notationRoot = board.Clone();
        string fen = root.ToFen(); int side = root.Side, budget = milliseconds;
        Guid id = searchId = Guid.NewGuid(); depths.Clear(); lastTrace = null; error = null;
        mode = analyze ? "analyze" : "play"; thinking = true;
        cancellation?.Dispose(); cancellation = new(); var token = cancellation.Token;
        Publish("state", SnapshotLocked());
        var observer = new SearchVisualization(view =>
        {
            lock (sync)
            {
                if (id != searchId) return;
                lastTrace = new(id, fen, side, view); Publish("trace", lastTrace);
            }
        });
        running = Task.Run(() =>
        {
            try
            {
                SearchResult result = search.Run(root, new SearchLimits(SoftMilliseconds: budget, HardMilliseconds: budget), token, info =>
                {
                    var variation = ChessNotation.Variation(notationRoot, info.Pv);
                    var analysis = new AnalysisView(id, fen, side, info.Depth, info.SelectiveDepth,
                        info.Score * (side == 0 ? 1 : -1), info.Nodes, info.Milliseconds, info.HashFull, variation);
                    lock (sync) { if (id == searchId) { depths.Add(analysis); Publish("analysis", analysis); } }
                }, observer);
                lock (sync)
                {
                    if (id != searchId) return;
                    if (board.ToFen() != fen) throw new InvalidOperationException("The game changed during search.");
                    if (!analyze && result.BestMove != Move.None && Outcome().Result == null) Apply(result.BestMove);
                    thinking = false; Publish("state", SnapshotLocked());
                }
            }
            catch (Exception problem)
            {
                lock (sync) { if (id == searchId) { thinking = false; error = problem.Message; Publish("state", SnapshotLocked()); } }
            }
        });
    }
    private void Apply(Move move)
    {
        string san = ChessNotation.San(board, move); int side = board.Side, number = board.FullmoveNumber;
        if (!board.TryMakeMove(move)) throw new InvalidOperationException("Aster returned an illegal move.");
        moves.Add(new(move.ToString(), san, board.ToFen(), side, number));
    }
    public async Task<PositionView> NewAsync(NewGame request)
    {
        Budget(request.Milliseconds);
        int side = request.Side switch { "white" => 0, "black" => 1, _ => throw new ArgumentException("Choose white or black.") };
        var fresh = new Board(string.IsNullOrWhiteSpace(request.Fen) ? Board.StartFen : request.Fen);
        int otherKing = BitOperations.TrailingZeroCount(fresh.Pieces[(fresh.Side ^ 1) * 6 + 5]);
        if (fresh.IsAttacked(otherKing, fresh.Side)) throw new ArgumentException("Invalid position: the side that just moved left its king in check.");
        await commands.WaitAsync();
        try
        {
            await CancelAndJoin(true);
            lock (sync)
            {
                board = fresh; startFen = board.ToFen(); humanSide = side; milliseconds = request.Milliseconds;
                moves.Clear(); depths.Clear(); lastTrace = null; error = null; mode = "play"; table.Clear();
                Publish("state", SnapshotLocked()); Start(); return SnapshotLocked();
            }
        }
        finally { commands.Release(); }
    }
    public async Task<PositionView> MoveAsync(string uci)
    {
        await commands.WaitAsync();
        try
        {
            lock (sync)
            {
                if (thinking || board.Side != humanSide) throw new InvalidOperationException("Wait for Aster's reply.");
                if (Outcome().Result != null) throw new InvalidOperationException("This game has finished.");
                Apply(board.ParseMove(uci)); Publish("state", SnapshotLocked()); Start(); return SnapshotLocked();
            }
        }
        finally { commands.Release(); }
    }
    public async Task<PositionView> UndoAsync()
    {
        await commands.WaitAsync();
        try
        {
            lock (sync) { if (!moves.Any(move => move.Side == humanSide)) throw new InvalidOperationException("You haven't made a move to take back."); }
            await CancelAndJoin(true);
            lock (sync)
            {
                while (moves.Count > 0)
                {
                    int side = moves[^1].Side; board.UnmakeMove(); moves.RemoveAt(moves.Count - 1);
                    if (side == humanSide) break;
                }
                table.Clear(); depths.Clear(); lastTrace = null; mode = "play"; error = null;
                Publish("state", SnapshotLocked()); return SnapshotLocked();
            }
        }
        finally { commands.Release(); }
    }
    public async Task<PositionView> StopAsync()
    {
        await commands.WaitAsync();
        try { await CancelAndJoin(false); lock (sync) { Publish("state", SnapshotLocked()); return SnapshotLocked(); } }
        finally { commands.Release(); }
    }
    public async Task<PositionView> AnalyzeAsync()
    {
        await commands.WaitAsync();
        try
        {
            lock (sync)
            {
                if (thinking) throw new InvalidOperationException("Stop the current search first.");
                if (Outcome().Result != null) throw new InvalidOperationException("This game has finished.");
                Start(true); return SnapshotLocked();
            }
        }
        finally { commands.Release(); }
    }
    public PositionView Configure(int value)
    { Budget(value); lock (sync) { milliseconds = value; Publish("state", SnapshotLocked()); return SnapshotLocked(); } }
    public string Pgn()
    {
        lock (sync)
        {
            string result = Outcome().Result ?? "*";
            var text = new StringBuilder($"[Event \"Aster visual play\"]\n[Site \"Local\"]\n[Date \"{DateTime.UtcNow:yyyy.MM.dd}\"]\n[White \"{(humanSide == 0 ? "You" : "Aster")}\"]\n[Black \"{(humanSide == 1 ? "You" : "Aster")}\"]\n[Result \"{result}\"]\n");
            if (startFen != Board.StartFen) text.Append($"[SetUp \"1\"]\n[FEN \"{startFen}\"]\n");
            text.Append('\n');
            for (int i = 0; i < moves.Count; i++)
            {
                var move = moves[i];
                if (move.Side == 0) text.Append($"{move.Number}. ");
                else if (i == 0) text.Append($"{move.Number}... ");
                text.Append(move.San).Append(' ');
            }
            return text.Append(result).Append('\n').ToString();
        }
    }
}
