using System.Globalization;

namespace Aster;

public sealed class Uci
{
    private Board position = new();
    private readonly TranspositionTable table = new();
    private readonly Search search;
    private Task? running;
    private Task? explaining;
    private CancellationTokenSource? cancellation;
    private readonly object outputLock = new();
    private int moveOverhead = 20;
    private NeuralNetwork? network;

    public Uci()
    {
        search = new Search(table);
#if ASTER_KPK || ASTER_CONVERSION
        KpkBitbase.Initialize();
#endif
#if ASTER_CONVERSION
        MajorMateBitbase.Initialize();
#endif
    }
    private void Write(string line)
    {
        lock (outputLock) { Console.WriteLine(line); Console.Out.Flush(); }
    }
    public async Task RunAsync()
    {
        string? line;
        while ((line = await Console.In.ReadLineAsync()) != null)
        {
            string[] tokens = line.Split(' ', StringSplitOptions.RemoveEmptyEntries);
            if (tokens.Length == 0) continue;
            try
            {
                switch (tokens[0])
                {
                    case "uci":
#if ASTER_LAZY_ORDER
                        Write("id name Aster 0.7.5-lazy-order-dev");
#elif ASTER_CONVERSION
                        Write("id name Aster 0.7.4-proof-dev");
#elif ASTER_KPK
                        Write("id name Aster 0.7.2-kpk-dev");
#elif ASTER_THREATS
                        Write("id name Aster 0.7.1-threat-dev");
#else
                        Write("id name Aster 0.7.4-feature-dev");
#endif
                        Write("id author Aster contributors");
                        Write("option name Hash type spin default 64 min 1 max 1024");
                        Write("option name Threads type spin default 1 min 1 max 1");
                        Write("option name Move Overhead type spin default 20 min 0 max 5000");
                        Write("option name EvalFile type string default <classical>");
                        Write("option name Clear Hash type button"); Write("uciok"); break;
                    case "isready": Write("readyok"); break;
                    case "ucinewgame": await StopAsync(); table.Clear(); position = new Board(network: network); break;
                    case "setoption": await StopAsync(); SetOption(tokens); break;
                    case "position": await StopAsync(); SetPosition(tokens); break;
                    case "go":
                        await StopAsync();
                        SearchLimits limits = ParseLimits(tokens);
                        Board root = position.Clone();
                        cancellation = new CancellationTokenSource();
                        CancellationToken token = cancellation.Token;
                        running = Task.Run(async () =>
                        {
                            try
                            {
                                SearchResult result = search.Run(root, limits, token, PrintInfo);
                                if (limits.Infinite && !token.IsCancellationRequested)
                                    try { await Task.Delay(Timeout.Infinite, token); } catch (OperationCanceledException) { }
                                Write($"bestmove {result.BestMove}");
                            }
                            catch (Exception error)
                            {
                                Write($"info string search error: {error.Message}");
                                Console.Error.WriteLine(error);
                                Environment.Exit(1);
                            }
                        });
                        break;
                    case "stop": await StopAsync(); break;
                    case "quit": await StopAsync(); return;
                    case "d": Write($"info string fen {position.ToFen()}"); break;
                    case "legal": PrintLegal(); break;
                    case "haslegal": Write($"info string haslegal {(position.HasAnyLegalMove() ? "true" : "false")}"); break;
                    case "eval": Write($"info string eval {Evaluation.Evaluate(position)}"); break;
                    case "explain":
                        if (explaining is { IsCompleted: false }) { Write("info string explanation busy"); break; }
                        Board explanationRoot = position.Clone();
                        explaining = Task.Run(() =>
                        {
                            try
                            {
                                StrategyProof explanation = EndgameProof.Build(explanationRoot);
                                Write("info string explanation " + System.Text.Json.JsonSerializer.Serialize(new
                                    { complete = explanation.Complete, reason = explanation.Reason, summary = explanation.Summary,
                                      positions = explanation.Nodes.Count, alternatives = explanation.Alternatives }));
                            }
                            catch (Exception error) { Write("info string explanation error " + System.Text.Json.JsonSerializer.Serialize(error.Message)); }
                        });
                        break;
                    case "kpk":
                        if (KpkBitbase.Probe(position, out bool pawnWin, out int conversion))
                            Write($"info string kpk {(pawnWin ? "win" : "draw")} {conversion}");
                        else Write("info string kpk unsupported");
                        break;
                    case "major":
                        if (MajorMateBitbase.Probe(position, out int strong, out bool won, out int distance))
                            Write($"info string major {(won ? "win" : "draw")} {strong} {distance}");
                        else Write("info string major unsupported");
                        break;
                    case "threats":
                        int[] threatFeatures = new int[7];
                        ThreatEvaluation.ExtractFeatures(position, threatFeatures);
                        Write($"info string threats {string.Join(' ', threatFeatures)} {ThreatEvaluation.WhiteCorrection(position, threatFeatures)}");
                        break;
                    case "nncheck":
                        if (network == null) Write("info string nncheck classical");
                        else Write($"info string nncheck {position.Neural!.WhiteScoreForSide(position.Side)} {network.EvaluateFromScratch(position)}");
                        break;
                    case "perft":
                        await StopAsync();
                        int depth = ParseInteger(tokens, 1, 0, 10);
                        Write($"info string perft {depth} {Perft.Count(position, depth)}"); break;
                    case "debug": break;
                }
            }
            catch (Exception error) when (error is FormatException or ArgumentException or OverflowException or IOException or UnauthorizedAccessException)
            { Write($"info string error: {error.Message}"); }
        }
        await StopAsync();
    }
    private void PrintLegal()
    {
        Span<Move> moves = stackalloc Move[256];
        int count = position.GenerateLegal(moves);
        Write("info string legal " + string.Join(' ', moves[..count].ToArray().Select(m => m.ToString()).Order()));
    }
    private async Task StopAsync()
    {
        if (running == null) return;
        cancellation?.Cancel();
        await running;
        running = null; cancellation?.Dispose(); cancellation = null;
    }
    private void SetOption(string[] tokens)
    {
        int nameIndex = Array.IndexOf(tokens, "name"), valueIndex = Array.IndexOf(tokens, "value");
        if (nameIndex < 0) throw new FormatException("setoption requires name.");
        string name = string.Join(' ', tokens[(nameIndex + 1)..(valueIndex < 0 ? tokens.Length : valueIndex)]).ToLowerInvariant();
        switch (name)
        {
            case "hash": table.Resize(ParseInteger(tokens, valueIndex + 1, 1, 1024)); break;
            case "threads": _ = ParseInteger(tokens, valueIndex + 1, 1, 1); break;
            case "move overhead": moveOverhead = ParseInteger(tokens, valueIndex + 1, 0, 5000); break;
            case "clear hash": table.Clear(); break;
            case "evalfile":
                if (valueIndex < 0) throw new FormatException("EvalFile requires a path or <classical>.");
                string path = string.Join(' ', tokens[(valueIndex + 1)..]);
                NeuralNetwork? loaded = path == "<classical>" ? null : NeuralNetwork.Load(path);
                position.SetNetwork(loaded); network = loaded; table.Clear();
                Write($"info string evaluator {(network == null ? "classical" : network.Name)}");
                break;
        }
    }
    private void SetPosition(string[] tokens)
    {
        if (tokens.Length < 2) throw new FormatException("position requires startpos or fen.");
        int index;
        Board next;
        if (tokens[1] == "startpos") { next = new Board(network: network); index = 2; }
        else if (tokens[1] == "fen" && tokens.Length >= 8) { next = new Board(string.Join(' ', tokens[2..8]), network); index = 8; }
        else throw new FormatException("Invalid position command.");
        if (index < tokens.Length)
        {
            if (tokens[index++] != "moves") throw new FormatException("Expected moves after position.");
            for (; index < tokens.Length; index++)
                if (!next.TryMakeMove(next.ParseMove(tokens[index]))) throw new FormatException("Illegal position move.");
        }
        position = next;
    }
    private SearchLimits ParseLimits(string[] tokens)
    {
        int depth = Search.MaxPly - 2, movesToGo = 30;
        long nodes = long.MaxValue, moveTime = -1, whiteTime = -1, blackTime = -1, whiteInc = 0, blackInc = 0;
        bool infinite = false, explicitLimit = false;
        Move[]? searchMoves = null;
        for (int i = 1; i < tokens.Length; i++)
        {
            switch (tokens[i])
            {
                case "depth": depth = ParseInteger(tokens, ++i, 1, Search.MaxPly - 2); explicitLimit = true; break;
                case "nodes": nodes = ParseLong(tokens, ++i, 1); explicitLimit = true; break;
                case "movetime": moveTime = ParseLong(tokens, ++i, 0); explicitLimit = true; break;
                case "wtime": whiteTime = ParseLong(tokens, ++i, 0); break;
                case "btime": blackTime = ParseLong(tokens, ++i, 0); break;
                case "winc": whiteInc = ParseLong(tokens, ++i, 0); break;
                case "binc": blackInc = ParseLong(tokens, ++i, 0); break;
                case "movestogo": movesToGo = ParseInteger(tokens, ++i, 1, 1000); break;
                case "infinite": infinite = true; break;
                case "ponder": throw new FormatException("Pondering is not supported.");
                case "searchmoves":
                    var selected = new List<Move>();
                    while (i + 1 < tokens.Length && LooksLikeMove(tokens[i + 1]))
                        selected.Add(position.ParseMove(tokens[++i]));
                    if (selected.Count == 0) throw new FormatException("searchmoves requires at least one legal move.");
                    searchMoves = selected.ToArray(); break;
                case "mate": depth = Math.Min(Search.MaxPly - 2, ParseInteger(tokens, ++i, 1, 63) * 2); explicitLimit = true; break;
            }
        }
        long soft = long.MaxValue, hard = long.MaxValue;
        if (!infinite)
        {
            long remaining = position.Side == 0 ? whiteTime : blackTime;
            long increment = position.Side == 0 ? whiteInc : blackInc;
            if (moveTime >= 0) soft = hard = Math.Max(1, moveTime - moveOverhead);
            else if (remaining >= 0)
            {
                long available = Math.Max(1, remaining - moveOverhead);
                soft = (long)Math.Clamp(remaining / (double)movesToGo + increment * 0.7, 1, available);
                hard = (long)Math.Min(available, Math.Max(soft, soft * 3.0));
            }
            else if (!explicitLimit) soft = hard = 1000;
        }
        return new SearchLimits(depth, nodes, soft, hard, infinite, searchMoves);
    }
    private static bool LooksLikeMove(string text) => text.Length is 4 or 5
        && text[0] is >= 'a' and <= 'h' && text[1] is >= '1' and <= '8'
        && text[2] is >= 'a' and <= 'h' && text[3] is >= '1' and <= '8'
        && (text.Length == 4 || "nbrq".Contains(text[4]));
    private static int ParseInteger(string[] tokens, int index, int min, int max)
    {
        if (index < 0 || index >= tokens.Length || !int.TryParse(tokens[index], NumberStyles.Integer, CultureInfo.InvariantCulture, out int value) || value < min || value > max)
            throw new FormatException($"Expected integer in [{min}, {max}].");
        return value;
    }
    private static long ParseLong(string[] tokens, int index, long min)
    {
        if (index < 0 || index >= tokens.Length || !long.TryParse(tokens[index], NumberStyles.Integer, CultureInfo.InvariantCulture, out long value) || value < min)
            throw new FormatException($"Expected integer >= {min}.");
        return value;
    }
    private void PrintInfo(SearchInfo info)
    {
        string score = Math.Abs(info.Score) > Search.MateThreshold
            ? $"mate {Math.Sign(info.Score) * ((Search.Mate - Math.Abs(info.Score) + 1) / 2)}" : $"cp {info.Score}";
        long nps = info.Nodes * 1000 / Math.Max(1, info.Milliseconds);
        Write($"info depth {info.Depth} seldepth {info.SelectiveDepth} score {score} nodes {info.Nodes} nps {nps} hashfull {info.HashFull} time {info.Milliseconds} pv {string.Join(' ', info.Pv.Select(m => m.ToString()))}");
    }
}
