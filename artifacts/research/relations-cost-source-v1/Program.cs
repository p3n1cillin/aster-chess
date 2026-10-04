using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using Aster;

if (args.Length != 4) throw new ArgumentException("Usage: RelationCost trace.json control.ann candidate.ann output.json");
if (File.Exists(args[3])) throw new IOException("Preserve prior timing evidence.");
using JsonDocument trace = JsonDocument.Parse(File.ReadAllText(args[0]));
JsonElement root = trace.RootElement;
int repetitions = root.GetProperty("repetitions").GetInt32();
string[] roles = ["classical", "control", "candidate"];
NeuralNetwork?[] models = [null, NeuralNetwork.Load(args[1]), NeuralNetwork.Load(args[2])];
var positions = root.GetProperty("positions").EnumerateArray().ToArray();
var work = new List<(Board Board, Move[] Moves, string Fen, ulong Key, int RootScore)>[3];
for (int role = 0; role < 3; role++)
{
    work[role] = [];
    foreach (JsonElement position in positions)
    {
        string fen = position.GetProperty("fen").GetString()!;
        var board = new Board(fen, models[role]);
        Move[] moves = position.GetProperty("moves").EnumerateArray().Select(m => board.ParseMove(m.GetString()!)).ToArray();
        if (moves.Length != 2) throw new ArgumentException("Each frozen root needs exactly two legal moves.");
        work[role].Add((board, moves, board.ToFen(), board.Key, Evaluation.Evaluate(board)));
    }
}
long Run(int role)
{
    long checksum = 0;
    for (int repeat = 0; repeat < repetitions; repeat++)
        foreach (var row in work[role])
            foreach (Move move in row.Moves)
            {
                if (!row.Board.TryMakeMove(move)) throw new InvalidOperationException("Frozen move is illegal.");
                try { checksum += Evaluation.Evaluate(row.Board); }
                finally { row.Board.UnmakeMove(); }
                checksum += Evaluation.Evaluate(row.Board);
            }
    foreach (var row in work[role])
        if (row.Board.ToFen() != row.Fen || row.Board.Key != row.Key || row.Board.Ply != 0 || Evaluation.Evaluate(row.Board) != row.RootScore)
            throw new InvalidOperationException("Evaluation/move trace failed root restoration.");
    return checksum;
}
long[] expected = new long[3];
for (int round = 0; round < root.GetProperty("warmup_rounds").GetInt32(); round++)
    for (int role = 0; role < 3; role++)
    {
        long checksum = Run(role);
        if (round == 0) expected[role] = checksum;
        else if (checksum != expected[role]) throw new InvalidOperationException("Warmup checksum changed.");
    }
var samples = new List<object>();
foreach (JsonElement round in root.GetProperty("orders").EnumerateArray())
    foreach (JsonElement roleValue in round.EnumerateArray())
    {
        int role = roleValue.GetInt32();
        var timer = Stopwatch.StartNew();
        long checksum = Run(role); timer.Stop();
        if (checksum != expected[role]) throw new InvalidOperationException("Measured checksum changed.");
        samples.Add(new { role = roles[role], milliseconds = timer.Elapsed.TotalMilliseconds, checksum });
    }
string Hash(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
var output = new { passed = true, trace_sha256 = Hash(args[0]), baseline_sha256 = Hash(typeof(Board).Assembly.Location),
    control_sha256 = Hash(args[1]), candidate_sha256 = Hash(args[2]),
    positions = positions.Length, repetitions, evaluations_per_round = positions.Length * 4 * repetitions,
    root_restoration_checked = true, warmup_rounds = root.GetProperty("warmup_rounds").GetInt32(), samples };
using var stream = new FileStream(args[3], FileMode.CreateNew, FileAccess.Write);
JsonSerializer.Serialize(stream, output, new JsonSerializerOptions { WriteIndented = true });
Console.WriteLine(JsonSerializer.Serialize(new { passed = true, positions = positions.Length, measured_samples = samples.Count }));
