namespace Aster;

public readonly record struct Move(int Value)
{
    public const int EnPassant = 1 << 15, Castle = 1 << 16, DoublePush = 1 << 17, Capture = 1 << 18;
    public static readonly Move None = default;
    public Move(int from, int to, int promotion = 0, int flags = 0)
        : this(from | (to << 6) | (promotion << 12) | flags) { }
    public int From => Value & 63;
    public int To => (Value >> 6) & 63;
    public int Promotion => (Value >> 12) & 7;
    public bool IsCapture => (Value & Capture) != 0;
    public bool IsEnPassant => (Value & EnPassant) != 0;
    public bool IsCastle => (Value & Castle) != 0;
    public bool IsDoublePush => (Value & DoublePush) != 0;
    public bool IsQuiet => !IsCapture && Promotion == 0;
    public override string ToString() => Value == 0 ? "0000" :
        SquareName(From) + SquareName(To) + (Promotion == 0 ? "" : " pnbrqk"[Promotion + 1].ToString());
    public static string SquareName(int square) => $"{(char)('a' + (square & 7))}{1 + (square >> 3)}";
    public static int ParseSquare(string value)
    {
        if (value.Length != 2 || value[0] < 'a' || value[0] > 'h' || value[1] < '1' || value[1] > '8')
            throw new FormatException($"Invalid square: {value}");
        return value[0] - 'a' + (value[1] - '1') * 8;
    }
}
