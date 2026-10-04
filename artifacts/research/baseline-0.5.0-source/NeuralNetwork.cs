using System.Numerics;

namespace Aster;

// Aster's own compact, symmetric 768 -> H -> 1 position network. This format
// intentionally does not read Stockfish networks or use Stockfish inference.
public sealed class NeuralNetwork
{
    public const int FeatureCount = 768, ActivationScale = 256, OutputScale = 256;
    public int Hidden { get; }
    public string Name { get; }
    public bool ClassicalBase { get; }
    internal readonly int[] Linear, Bias, Weights, Output;
    public NeuralNetwork(int hidden, short[] linear, short[] bias, short[] weights, short[] output, string name = "unnamed", bool classicalBase = false)
    {
        if (hidden is < 8 or > 256 || hidden % 8 != 0 || linear.Length != FeatureCount
            || bias.Length != hidden || weights.Length != FeatureCount * hidden || output.Length != hidden)
            throw new ArgumentException("Invalid neural network dimensions.");
        Hidden = hidden; Name = name; ClassicalBase = classicalBase;
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
        if (version is not (1 or 2) || features != FeatureCount || hidden is < 8 or > 256 || hidden % 8 != 0
            || activationScale != ActivationScale || outputScale != OutputScale)
            throw new FormatException("Unsupported Aster neural network format.");
        long expected = 28 + 2L * (FeatureCount + 2 * hidden + FeatureCount * hidden);
        if (stream.Length != expected) throw new FormatException("Incorrect neural network payload length.");
        short[] Read(int n)
        {
            var values = new short[n];
            for (int i = 0; i < n; i++) values[i] = reader.ReadInt16();
            return values;
        }
        return new NeuralNetwork(hidden, Read(FeatureCount), Read(hidden), Read(FeatureCount * hidden), Read(hidden), Path.GetFileName(path), version == 2);
    }
    public void Save(string path)
    {
        using var writer = new BinaryWriter(File.Create(path));
        writer.Write("ASTNN001"u8.ToArray()); writer.Write(ClassicalBase ? 2 : 1); writer.Write(FeatureCount); writer.Write(Hidden);
        writer.Write(ActivationScale); writer.Write(OutputScale);
        foreach (int[] values in new[] { Linear, Bias, Weights, Output })
            foreach (int value in values) writer.Write((short)value);
    }
    public static int Feature(int piece, int square, int perspective) =>
        (perspective == 0 ? piece : (piece + 6) % 12) * 64 + (perspective == 0 ? square : square ^ 56);

    public int EvaluateFromScratch(Board board)
    {
        var state = new NeuralAccumulator(this);
        for (int square = 0; square < 64; square++)
            if (board.Squares[square] >= 0) state.Update(board.Squares[square], square, 1);
        return state.WhiteScore;
    }
}

public sealed class NeuralAccumulator
{
    public NeuralNetwork Model { get; }
    private readonly int[] accumulated;
    private readonly int[] linear = new int[2];
    private readonly int[] deltas = new int[NeuralNetwork.FeatureCount], dirty = new int[NeuralNetwork.FeatureCount];
    private readonly bool[] listed = new bool[NeuralNetwork.FeatureCount];
    private int dirtyCount, cachedScore;
    private bool cacheValid;
    public NeuralAccumulator(NeuralNetwork model)
    {
        Model = model; accumulated = new int[model.Hidden * 2]; Reset();
    }
    public void Reset()
    {
        Array.Clear(linear);
        Array.Clear(deltas); Array.Clear(listed); dirtyCount = 0; cacheValid = false;
        Model.Bias.CopyTo(accumulated, 0); Model.Bias.CopyTo(accumulated, Model.Hidden);
    }
    public void Update(int piece, int square, int sign)
    {
        int feature = piece * 64 + square;
        if (!listed[feature]) { listed[feature] = true; dirty[dirtyCount++] = feature; }
        deltas[feature] += sign;
    }
    private void Flush()
    {
        for (int i = 0; i < dirtyCount; i++)
        {
            int feature = dirty[i], delta = deltas[feature];
            if (delta != 0) { Apply(feature / 64, feature % 64, delta); cacheValid = false; }
            deltas[feature] = 0; listed[feature] = false;
        }
        dirtyCount = 0;
    }
    private void Apply(int piece, int square, int sign)
    {
        int hidden = Model.Hidden;
        for (int perspective = 0; perspective < 2; perspective++)
        {
            int feature = NeuralNetwork.Feature(piece, square, perspective), offset = perspective * hidden, weightOffset = feature * hidden;
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
    public int WhiteScore
    {
        get
        {
            Flush();
            if (cacheValid) return cachedScore;
            long residual = 0;
            for (int i = 0; i < Model.Hidden; i++)
                residual += (long)(Math.Clamp(accumulated[i], 0, NeuralNetwork.ActivationScale)
                    - Math.Clamp(accumulated[i + Model.Hidden], 0, NeuralNetwork.ActivationScale)) * Model.Output[i];
            cachedScore = (linear[0] - linear[1]) / 2 + (int)(residual / (NeuralNetwork.ActivationScale * NeuralNetwork.OutputScale));
            cacheValid = true;
            return cachedScore;
        }
    }
}
