using System.Diagnostics;
using System.Text.Json;

namespace Aster;

public static class Program
{
    public static async Task<int> Main(string[] args)
    {
        try
        {
            if (args.Length == 0) { await new Uci().RunAsync(); return 0; }
            switch (args[0])
            {
                case "certify-mate":
                    if (args.Length < 5) throw new ArgumentException("certify-mate requires a new output path, plies0..7, white|black and FEN.");
                    int matePlies = int.Parse(args[2]);
                    int attacker = args[3] switch { "white" => 0, "black" => 1, _ => throw new ArgumentException("Expected white or black.") };
                    MateStrategyProof mateProof = MateProof.Build(new Board(string.Join(' ', args[4..])), attacker, matePlies);
                    if (!mateProof.Complete) { Console.Error.WriteLine(mateProof.Summary); return 2; }
                    // CreateNew closes the race between checking and writing.
                    using (var certificate = new FileStream(args[1], FileMode.CreateNew, FileAccess.Write))
                        JsonSerializer.Serialize(certificate, mateProof, new JsonSerializerOptions
                            { PropertyNamingPolicy = JsonNamingPolicy.CamelCase, WriteIndented = true });
                    Console.WriteLine(mateProof.Summary); return 0;
                case "certify":
                    if (args.Length < 3) throw new ArgumentException("certify requires a new output path and FEN.");
                    if (File.Exists(args[1])) throw new IOException("Preserve existing strategy certificates.");
                    StrategyProof proof = EndgameProof.Build(new Board(string.Join(' ', args[2..])));
                    if (!proof.Complete) { Console.Error.WriteLine(proof.Summary); return 2; }
                    File.WriteAllText(args[1], JsonSerializer.Serialize(proof, new JsonSerializerOptions
                        { PropertyNamingPolicy = JsonNamingPolicy.CamelCase, WriteIndented = true }));
                    Console.WriteLine(proof.Summary); return 0;
                case "majordump":
                    if (args.Length != 3 || args[1] is not ("queen" or "rook"))
                        throw new ArgumentException("majordump requires queen|rook and an output path.");
                    MajorMateBitbase.Export(args[2], args[1] == "queen");
                    Console.WriteLine(JsonSerializer.Serialize(new { output = Path.GetFullPath(args[2]) }));
                    return 0;
                case "kpkdump":
                    if (args.Length != 2) throw new ArgumentException("kpkdump requires an output path.");
                    KpkBitbase.Export(args[1]);
                    Console.WriteLine(JsonSerializer.Serialize(new { output = Path.GetFullPath(args[1]) }));
                    return 0;
                case "perft":
                    int depth = args.Length >= 2 ? int.Parse(args[1]) : 5;
                    if (depth is < 0 or > 10) throw new ArgumentException("Perft depth must be 0..10.");
                    var board = new Board(args.Length >= 3 ? string.Join(' ', args[2..]) : Board.StartFen);
                    var timer = Stopwatch.StartNew();
                    long nodes = Perft.Count(board, depth);
                    Console.WriteLine(JsonSerializer.Serialize(new { depth, nodes, milliseconds = timer.ElapsedMilliseconds }));
                    return 0;
                case "bench":
                    int benchDepth = args.Length >= 2 ? int.Parse(args[1]) : 6;
                    if (benchDepth is < 1 or > 20) throw new ArgumentException("Benchmark depth must be 1..20.");
                    string[] positions =
                    [
                        Board.StartFen,
                        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
                        "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
                        "r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P4/2PBPN2/PP1N1PPP/R1BQ1RK1 w - - 0 8",
                        "6k1/5ppp/8/8/8/8/5PPP/3Q2K1 w - - 0 1"
                    ];
                    long totalNodes = 0;
                    NeuralNetwork? network = args.Length >= 3 ? NeuralNetwork.Load(string.Join(' ', args[2..])) : null;
                    var benchTimer = Stopwatch.StartNew();
                    var table = new TranspositionTable();
                    foreach (string fen in positions)
                    {
                        table.Clear();
                        SearchResult result = new Search(table).Run(new Board(fen, network), new SearchLimits(benchDepth));
                        totalNodes += result.Nodes;
                        Console.WriteLine(JsonSerializer.Serialize(new { fen, bestmove = result.BestMove.ToString(), result.Score, result.Depth, result.Nodes, result.Milliseconds
#if ASTER_PROFILE
                            , profile = SearchProfile.Snapshot()
#endif
                        }));
                    }
                    Console.WriteLine(JsonSerializer.Serialize(new { totalNodes, milliseconds = benchTimer.ElapsedMilliseconds, nps = totalNodes * 1000 / Math.Max(1, benchTimer.ElapsedMilliseconds) }));
                    return 0;
                default:
                    Console.Error.WriteLine("Usage: Aster [perft [depth] [fen] | bench [depth] [evalfile] | kpkdump <path> | majordump queen|rook <path> | certify <path> <fen> | certify-mate <path> <plies0..7> <white|black> <fen>]; no arguments starts UCI."); return 2;
            }
        }
        catch (Exception error) when (error is ArgumentException or FormatException or OverflowException or IOException or UnauthorizedAccessException)
        { Console.Error.WriteLine(error.Message); return 2; }
    }
}
