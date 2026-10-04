namespace Aster;

public static class Perft
{
    public static long Count(Board board, int depth)
    {
        if (depth < 0) throw new ArgumentOutOfRangeException(nameof(depth));
        if (depth == 0) return 1;
        Span<Move> moves = stackalloc Move[256];
        int count = board.GeneratePseudoLegal(moves);
        long nodes = 0;
        for (int i = 0; i < count; i++)
            if (board.TryMakeMove(moves[i]))
            {
                nodes += depth == 1 ? 1 : Count(board, depth - 1);
                board.UnmakeMove();
            }
        return nodes;
    }
}
