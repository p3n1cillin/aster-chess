namespace Aster;

public static class Zobrist
{
    public static readonly ulong[,] Piece = new ulong[12, 64];
    public static readonly ulong[] Castling = new ulong[16], EnPassant = new ulong[8], Rule50 = new ulong[101];
    public static readonly ulong Side;
    static Zobrist()
    {
        ulong state = 0xA57E202610030001;
        ulong Next()
        {
            state += 0x9E3779B97F4A7C15;
            ulong z = state;
            z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9;
            z = (z ^ (z >> 27)) * 0x94D049BB133111EB;
            return z ^ (z >> 31);
        }
        for (int p = 0; p < 12; p++) for (int s = 0; s < 64; s++) Piece[p, s] = Next();
        for (int i = 0; i < 16; i++) Castling[i] = Next();
        for (int i = 0; i < 8; i++) EnPassant[i] = Next();
        for (int i = 0; i <= 100; i++) Rule50[i] = Next();
        Side = Next();
    }
}
