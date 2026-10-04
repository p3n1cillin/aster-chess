using System.Numerics;

namespace Aster;

// Aster's own symmetric piece-square/king-context position network. This format
// intentionally does not read Stockfish networks or use Stockfish inference.
public sealed class NeuralNetwork
{
    public const int FeatureCount = 768, ActivationScale = 256, OutputScale = 256;
    public const int KingBuckets = 16, ContextFeatureCount = FeatureCount * (KingBuckets + 1);
    public int Hidden { get; }
    public string Name { get; }
    public bool ClassicalBase { get; }
    public bool HasKingContext { get; }
    public bool HasTurnOutput { get; }
    public int Features => HasKingContext ? ContextFeatureCount : FeatureCount;
    internal readonly int[] Linear, Bias, Weights, Output;
    public NeuralNetwork(int hidden, short[] linear, short[] bias, short[] weights, short[] output, string name = "unnamed", bool classicalBase = false, bool kingContext = false, bool turnOutput = false)
    {
        int features = kingContext ? ContextFeatureCount : FeatureCount;
        if (hidden is < 8 or > 256 || hidden % 8 != 0 || linear.Length != features
            || bias.Length != hidden || weights.Length != features * hidden || output.Length != hidden * (turnOutput ? 2 : 1)
            || (turnOutput && !kingContext))
            throw new ArgumentException("Invalid neural network dimensions.");
        Hidden = hidden; Name = name; ClassicalBase = classicalBase; HasKingContext = kingContext;
        HasTurnOutput = turnOutput;
        Linear = Array.ConvertAll(linear, x => (int)x); Bias = Array.ConvertAll(bias, x => (int)x);
        Weights = Array.ConvertAll(weights, x => (int)x); Output = Array.ConvertAll(output, x => (int)x);
    }
    public static NeuralNetwork Load(string path)
    {
        using var stream = File.OpenRead(path);
        using var reader = new BinaryReader(stream);
        if (!reader.ReadBytes(8).SequenceEqual("ASTNN001"u8.ToArray())) throw new FormatException("Invalid Aster neural network magic.");
        int version = reader.ReadInt32(), features = reader.ReadInt32(), hidden = reader.ReadInt32();
        int activationScale = reader.ReadInt32(), outputScale = reader.ReadInt32();
        bool context = version >= 3, turnOutput = version is 5 or 6;
        if (version is < 1 or > 6 || features != (context ? ContextFeatureCount : FeatureCount) || hidden is < 8 or > 256 || hidden % 8 != 0
            || activationScale != ActivationScale || outputScale != OutputScale)
            throw new FormatException("Unsupported Aster neural network format.");
        int outputs = hidden * (turnOutput ? 2 : 1);
        long expected = 28 + 2L * (features + hidden + outputs + features * hidden);
        if (stream.Length != expected) throw new FormatException("Incorrect neural network payload length.");
        short[] Read(int n)
        {
            var values = new short[n];
            for (int i = 0; i < n; i++) values[i] = reader.ReadInt16();
            return values;
        }
        return new NeuralNetwork(hidden, Read(features), Read(hidden), Read(features * hidden), Read(outputs), Path.GetFileName(path), version is 2 or 3 or 5, context, turnOutput);
    }
    public void Save(string path)
    {
        using var writer = new BinaryWriter(File.Create(path));
        writer.Write("ASTNN001"u8.ToArray()); writer.Write(HasTurnOutput ? (ClassicalBase ? 5 : 6) : HasKingContext ? (ClassicalBase ? 3 : 4) : (ClassicalBase ? 2 : 1)); writer.Write(Features); writer.Write(Hidden);
        writer.Write(ActivationScale); writer.Write(OutputScale);
        foreach (int[] values in new[] { Linear, Bias, Weights, Output })
            foreach (int value in values) writer.Write((short)value);
    }
    public static int Feature(int piece, int square, int perspective) =>
        (perspective == 0 ? piece : (piece + 6) % 12) * 64 + (perspective == 0 ? square : square ^ 56);
    public static int KingBucket(int square, int perspective)
    {
        int oriented = perspective == 0 ? square : square ^ 56;
        return (oriented >> 4) * 4 + (oriented & 7) / 2;
    }

    public int EvaluateFromScratch(Board board)
    {
        var state = new NeuralAccumulator(this);
        for (int square = 0; square < 64; square++)
            if (board.Squares[square] >= 0) state.Update(board.Squares[square], square, 1);
        return state.WhiteScoreForSide(board.Side);
    }
}

public sealed class NeuralAccumulator
{
    public NeuralNetwork Model { get; }
    private readonly int[] accumulated;
    private readonly int[] linear = new int[2];
    private readonly int[] deltas = new int[NeuralNetwork.FeatureCount], dirty = new int[NeuralNetwork.FeatureCount];
    private readonly bool[] listed = new bool[NeuralNetwork.FeatureCount];
    private readonly ulong[]? present;
    private readonly int[] kingBuckets = [-1, -1];
    private int dirtyCount;
    private readonly int[] cachedScores = new int[2];
    private readonly bool[] cacheValid = new bool[2];
    public NeuralAccumulator(NeuralNetwork model)
    {
        Model = model; accumulated = new int[model.Hidden * 2];
        if (model.HasKingContext) present = new ulong[12];
        Reset();
    }
    public void Reset()
    {
        Array.Clear(linear);
        Array.Clear(deltas); Array.Clear(listed); dirtyCount = 0; Array.Clear(cacheValid);
        if (present != null) Array.Clear(present);
        Array.Fill(kingBuckets, -1);
        Model.Bias.CopyTo(accumulated, 0); Model.Bias.CopyTo(accumulated, Model.Hidden);
    }
    public void Update(int piece, int square, int sign)
    {
        int feature = piece * 64 + square;
        if (!listed[feature]) { listed[feature] = true; dirty[dirtyCount++] = feature; }
        deltas[feature] += sign;
        if (present != null)
        {
            if (sign > 0) present[piece] |= 1UL << square;
            else present[piece] &= ~(1UL << square);
        }
    }
    private void Flush()
    {
        if (present != null)
        {
            FlushContext();
            return;
        }
        for (int i = 0; i < dirtyCount; i++)
        {
            int feature = dirty[i], delta = deltas[feature];
            if (delta != 0) { Apply(feature / 64, feature % 64, delta); cacheValid[0] = cacheValid[1] = false; }
            deltas[feature] = 0; listed[feature] = false;
        }
        dirtyCount = 0;
    }
    private void Apply(int piece, int square, int sign)
    {
        for (int perspective = 0; perspective < 2; perspective++)
            ApplyFeature(NeuralNetwork.Feature(piece, square, perspective), perspective, sign);
    }
    private void FlushContext()
    {
        for (int perspective = 0; perspective < 2; perspective++)
        {
            ulong king = present![perspective * 6 + 5];
            if (BitOperations.PopCount(king) != 1) throw new InvalidOperationException("King-context inference requires one king per color.");
            int bucket = NeuralNetwork.KingBucket(BitOperations.TrailingZeroCount(king), perspective);
            if (kingBuckets[perspective] != bucket)
            {
                Model.Bias.CopyTo(accumulated, perspective * Model.Hidden); linear[perspective] = 0;
                for (int piece = 0; piece < 12; piece++)
                {
                    ulong remaining = present[piece];
                    while (remaining != 0) ApplyContext(piece, Attacks.Pop(ref remaining), perspective, bucket, 1);
                }
                kingBuckets[perspective] = bucket; cacheValid[0] = cacheValid[1] = false;
            }
            else
                for (int i = 0; i < dirtyCount; i++)
                {
                    int feature = dirty[i], delta = deltas[feature];
                    if (delta == 0) continue;
                    ApplyContext(feature / 64, feature % 64, perspective, bucket, delta); cacheValid[0] = cacheValid[1] = false;
                }
        }
        for (int i = 0; i < dirtyCount; i++) { deltas[dirty[i]] = 0; listed[dirty[i]] = false; }
        dirtyCount = 0;
    }
    private void ApplyContext(int piece, int square, int perspective, int bucket, int sign)
    {
        int feature = NeuralNetwork.Feature(piece, square, perspective);
        ApplyFeature(feature, perspective, sign);
        ApplyFeature(NeuralNetwork.FeatureCount * (bucket + 1) + feature, perspective, sign);
    }
    private void ApplyFeature(int feature, int perspective, int sign)
    {
        int hidden = Model.Hidden;
        {
            int offset = perspective * hidden, weightOffset = feature * hidden;
            linear[perspective] += Model.Linear[feature] * sign;
            int i = 0;
            if (Vector.IsHardwareAccelerated)
                for (; i <= hidden - Vector<int>.Count; i += Vector<int>.Count)
                {
                    var previous = new Vector<int>(accumulated.AsSpan(offset + i));
                    var weights = new Vector<int>(Model.Weights.AsSpan(weightOffset + i));
                    (previous + weights * new Vector<int>(sign)).CopyTo(accumulated, offset + i);
                }
            for (; i < hidden; i++) accumulated[offset + i] += Model.Weights[weightOffset + i] * sign;
        }
    }
    public int WhiteScore => WhiteScoreForSide(0);
    public int WhiteScoreForSide(int side)
    {
            if ((uint)side > 1) throw new ArgumentOutOfRangeException(nameof(side));
            if (!Model.HasTurnOutput) side = 0;
            Flush();
            if (cacheValid[side]) return cachedScores[side];
            long residual = 0;
            int i = 0;
            int ownOffset = side * Model.Hidden, otherOffset = (1 - side) * Model.Hidden;
            if (Vector.IsHardwareAccelerated)
            {
                var ceiling = new Vector<int>(NeuralNetwork.ActivationScale);
                for (; i <= Model.Hidden - Vector<int>.Count; i += Vector<int>.Count)
                {
                    var white = Vector.Min(Vector.Max(new Vector<int>(accumulated.AsSpan(i + ownOffset)), Vector<int>.Zero), ceiling);
                    var black = Vector.Min(Vector.Max(new Vector<int>(accumulated.AsSpan(i + otherOffset)), Vector<int>.Zero), ceiling);
                    // Each lane is bounded by 256 * 32768; a SIMD dot fits
                    // int32, while the sum across 256 outputs requires int64.
                    if (Model.HasTurnOutput)
                    {
                        residual += Vector.Dot(white, new Vector<int>(Model.Output.AsSpan(i)));
                        residual += Vector.Dot(black, new Vector<int>(Model.Output.AsSpan(i + Model.Hidden)));
                    }
                    else residual += Vector.Dot(white - black, new Vector<int>(Model.Output.AsSpan(i)));
                }
            }
            for (; i < Model.Hidden; i++)
            {
                int own = Math.Clamp(accumulated[i + ownOffset], 0, NeuralNetwork.ActivationScale);
                int other = Math.Clamp(accumulated[i + otherOffset], 0, NeuralNetwork.ActivationScale);
                residual += Model.HasTurnOutput ? (long)own * Model.Output[i] + (long)other * Model.Output[i + Model.Hidden]
                    : (long)(own - other) * Model.Output[i];
            }
            if (side == 1) residual = -residual;
            cachedScores[side] = (linear[0] - linear[1]) / 2 + (int)(residual / (NeuralNetwork.ActivationScale * NeuralNetwork.OutputScale));
            cacheValid[side] = true;
            return cachedScores[side];
    }
}
