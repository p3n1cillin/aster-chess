namespace Aster;

public enum Bound : byte { None, Exact, Lower, Upper }

public sealed class TranspositionTable
{
    private struct Entry
    {
        public ulong Key;
        public Move Move;
        public short Score, Depth;
        public Bound Bound;
        public byte Age;
    }
    private Entry[] entries = [];
    private int mask;
    private byte age;
    public int Megabytes { get; private set; }
    public TranspositionTable(int megabytes = 64) => Resize(megabytes);
    public void Resize(int megabytes)
    {
        if (megabytes is < 1 or > 1024) throw new ArgumentOutOfRangeException(nameof(megabytes));
        int size = 1;
        while ((long)size * 2 * 24 <= (long)megabytes * 1024 * 1024) size *= 2;
        entries = new Entry[size]; mask = size - 1; Megabytes = megabytes;
    }
    public void Clear() => Array.Clear(entries);
    public void NewSearch() => age++;
    public bool Probe(ulong key, int ply, out Move move, out int score, out int depth, out Bound bound)
    {
        ref Entry entry = ref entries[(int)(key & (uint)mask)];
        move = Move.None; score = 0; depth = 0; bound = Bound.None;
        if (entry.Bound == Bound.None || entry.Key != key) return false;
        move = entry.Move; score = entry.Score; depth = entry.Depth; bound = entry.Bound;
        if (score > Search.MateThreshold) score -= ply;
        if (score < -Search.MateThreshold) score += ply;
        return true;
    }
    public void Store(ulong key, Move move, int score, int depth, Bound bound, int ply)
    {
        ref Entry entry = ref entries[(int)(key & (uint)mask)];
        if (entry.Key != key && entry.Age == age && entry.Depth > depth + 3) return;
        // A horizon result cannot replace a deeper search of the same position.
        if (entry.Key == key && entry.Depth > depth && (depth == 0 || bound != Bound.Exact || entry.Bound == Bound.Exact)) return;
        if (score > Search.MateThreshold) score += ply;
        if (score < -Search.MateThreshold) score -= ply;
        entry = new Entry { Key = key, Move = move, Score = (short)score, Depth = (short)depth, Bound = bound, Age = age };
    }
    public int HashFull
    {
        get
        {
            int used = 0, count = Math.Min(1000, entries.Length);
            for (int i = 0; i < count; i++) if (entries[i].Bound != Bound.None && entries[i].Age == age) used++;
            return used * 1000 / count;
        }
    }
}
