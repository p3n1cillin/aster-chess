using System.Numerics;
using System.Text;

namespace Aster;

public sealed class Board
{
    public const string StartFen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
    public const string PieceSymbols = "PNBRQKpnbrqk";
    public readonly int[] Squares = new int[64];
    public readonly ulong[] Pieces = new ulong[12];
    public readonly ulong[] Colors = new ulong[2];
    public ulong Occupied => Colors[0] | Colors[1];
    public int Side { get; private set; }
    public int Castling { get; private set; }
    public int EpSquare { get; private set; } = -1;
    public int HalfmoveClock { get; private set; }
    public int FullmoveNumber { get; private set; } = 1;
    public ulong Key { get; private set; }
    public ulong SearchKey => Key ^ Zobrist.Rule50[Math.Min(100, HalfmoveClock)];
    public int MgScore { get; private set; }
    public int EgScore { get; private set; }
    public int Phase { get; private set; }
    public int Ply { get; private set; }
    public NeuralAccumulator? Neural { get; private set; }
    private readonly Undo[] undo = new Undo[4096];
    private readonly ulong[] history = new ulong[4097];
    private int repetitionFloor;
    private readonly record struct Undo(Move Move, int Captured, int CapturedSquare, int Castling,
        int Ep, int Halfmove, int Fullmove, ulong Key, int RepetitionFloor);

    public Board(string fen = StartFen, NeuralNetwork? network = null)
    {
        if (network != null) Neural = new NeuralAccumulator(network);
        LoadFen(fen);
    }
    public void SetNetwork(NeuralNetwork? network)
    {
        Neural = network == null ? null : new NeuralAccumulator(network);
        if (Neural != null)
            for (int square = 0; square < 64; square++)
                if (Squares[square] >= 0) Neural.Update(Squares[square], square, 1);
    }

    public Board Clone()
    {
        var copy = new Board(ToFen(), Neural?.Model);
        copy.Ply = Ply;
        copy.repetitionFloor = repetitionFloor;
        Array.Copy(undo, copy.undo, Ply);
        Array.Copy(history, copy.history, Ply + 1);
        return copy;
    }

    public void LoadFen(string fen)
    {
        var parts = fen.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length != 6) throw new FormatException("FEN must have six fields.");
        Array.Fill(Squares, -1);
        Array.Clear(Pieces); Array.Clear(Colors);
        Key = 0; MgScore = 0; EgScore = 0; Phase = 0; Ply = 0; repetitionFloor = 0;
        Neural?.Reset();
        var ranks = parts[0].Split('/');
        if (ranks.Length != 8) throw new FormatException("FEN must have eight ranks.");
        for (int r = 0; r < 8; r++)
        {
            int file = 0;
            foreach (char c in ranks[r])
            {
                if (c >= '1' && c <= '8') file += c - '0';
                else
                {
                    int piece = PieceSymbols.IndexOf(c);
                    if (piece < 0 || file >= 8) throw new FormatException("Invalid FEN piece placement.");
                    Put(piece, (7 - r) * 8 + file++);
                }
                if (file > 8) throw new FormatException("FEN rank is too wide.");
            }
            if (file != 8) throw new FormatException("FEN rank is too short.");
        }
        if (BitOperations.PopCount(Pieces[5]) != 1 || BitOperations.PopCount(Pieces[11]) != 1)
            throw new FormatException("FEN must contain exactly one king per side.");
        if (((Pieces[0] | Pieces[6]) & 0xFF000000000000FFUL) != 0)
            throw new FormatException("Pawns cannot occupy the first or eighth rank.");
        Side = parts[1] switch { "w" => 0, "b" => 1, _ => throw new FormatException("Invalid FEN side.") };
        Castling = 0;
        if (parts[2] != "-")
            foreach (char c in parts[2]) Castling |= c switch
            { 'K' => 1, 'Q' => 2, 'k' => 4, 'q' => 8, _ => throw new FormatException("Invalid castling rights.") };
        EpSquare = parts[3] == "-" ? -1 : Move.ParseSquare(parts[3]);
        if (EpSquare >= 0 && ((EpSquare >> 3) != (Side == 0 ? 5 : 2) || Squares[EpSquare] != -1 || Squares[EpSquare + (Side == 0 ? -8 : 8)] != (Side ^ 1) * 6))
            throw new FormatException("Invalid en passant target.");
        if (!int.TryParse(parts[4], out int half) || half < 0 || !int.TryParse(parts[5], out int full) || full < 1)
            throw new FormatException("Invalid FEN move counters.");
        HalfmoveClock = half; FullmoveNumber = full;
        Key ^= Zobrist.Castling[Castling];
        if (Side == 1) Key ^= Zobrist.Side;
        Key ^= EpKey();
        history[0] = Key;
    }

    private void Put(int piece, int square)
    {
        Squares[square] = piece;
        ulong bit = 1UL << square;
        Pieces[piece] |= bit; Colors[piece / 6] |= bit;
        Key ^= Zobrist.Piece[piece, square];
        MgScore += Evaluation.Mg[piece, square]; EgScore += Evaluation.Eg[piece, square];
        Phase += Evaluation.PhaseWeight[piece % 6];
        Neural?.Update(piece, square, 1);
    }
    private void Remove(int piece, int square)
    {
        Squares[square] = -1;
        ulong bit = ~(1UL << square);
        Pieces[piece] &= bit; Colors[piece / 6] &= bit;
        Key ^= Zobrist.Piece[piece, square];
        MgScore -= Evaluation.Mg[piece, square]; EgScore -= Evaluation.Eg[piece, square];
        Phase -= Evaluation.PhaseWeight[piece % 6];
        Neural?.Update(piece, square, -1);
    }

    public bool IsAttacked(int square, int byColor) => IsAttacked(square, byColor, Occupied);
    public bool IsAttacked(int square, int byColor, ulong occupied, ulong removed = 0)
    {
        int p = byColor * 6;
        return (Attacks.Pawn[byColor ^ 1, square] & Pieces[p] & ~removed) != 0
            || (Attacks.Knight[square] & Pieces[p + 1] & ~removed) != 0
            || (Attacks.King[square] & Pieces[p + 5] & ~removed) != 0
            || (Attacks.Bishop(square, occupied) & (Pieces[p + 2] | Pieces[p + 4]) & ~removed) != 0
            || (Attacks.Rook(square, occupied) & (Pieces[p + 3] | Pieces[p + 4]) & ~removed) != 0;
    }
    public bool InCheck => IsAttacked(BitOperations.TrailingZeroCount(Pieces[Side * 6 + 5]), Side ^ 1);

    private ulong EpKey()
    {
        if (EpSquare < 0) return 0;
        ulong candidates = Attacks.Pawn[Side ^ 1, EpSquare] & Pieces[Side * 6];
        int capturedSquare = EpSquare + (Side == 0 ? -8 : 8);
        ulong captured = 1UL << capturedSquare;
        int king = BitOperations.TrailingZeroCount(Pieces[Side * 6 + 5]);
        while (candidates != 0)
        {
            int from = Attacks.Pop(ref candidates);
            ulong occupied = (Occupied & ~(captured | (1UL << from))) | (1UL << EpSquare);
            if (!IsAttacked(king, Side ^ 1, occupied, captured)) return Zobrist.EnPassant[EpSquare & 7];
        }
        return 0;
    }

    // Input must be generated by GeneratePseudoLegal; illegal king exposure is undone here.
    public bool TryMakeMove(Move move)
    {
        MakeUnchecked(move);
        int previousSide = Side ^ 1;
        if (!IsAttacked(BitOperations.TrailingZeroCount(Pieces[previousSide * 6 + 5]), Side)) return true;
        UnmakeMove();
        return false;
    }

    private void MakeUnchecked(Move move)
    {
        if (Ply >= undo.Length) throw new InvalidOperationException("Position history capacity exceeded.");
        int piece = Squares[move.From];
        int capturedSquare = move.IsEnPassant ? move.To + (Side == 0 ? -8 : 8) : move.To;
        int captured = Squares[capturedSquare];
        undo[Ply++] = new Undo(move, captured, capturedSquare, Castling, EpSquare, HalfmoveClock, FullmoveNumber, Key, repetitionFloor);
        Key ^= EpKey() ^ Zobrist.Castling[Castling];
        Remove(piece, move.From);
        if (captured >= 0) Remove(captured, capturedSquare);
        Put(move.Promotion == 0 ? piece : Side * 6 + move.Promotion, move.To);
        if (move.IsCastle)
        {
            int rookFrom = move.To > move.From ? move.From + 3 : move.From - 4;
            int rookTo = move.To > move.From ? move.From + 1 : move.From - 1;
            Remove(Side * 6 + 3, rookFrom); Put(Side * 6 + 3, rookTo);
        }
        Castling &= RightsMask(move.From) & RightsMask(move.To);
        EpSquare = move.IsDoublePush ? (move.From + move.To) / 2 : -1;
        HalfmoveClock = piece % 6 == 0 || captured >= 0 ? 0 : HalfmoveClock + 1;
        if (Side == 1) FullmoveNumber++;
        Side ^= 1; Key ^= Zobrist.Side ^ Zobrist.Castling[Castling] ^ EpKey();
        history[Ply] = Key;
    }

    public void MakeNullMove()
    {
        if (Ply >= undo.Length) throw new InvalidOperationException("Position history capacity exceeded.");
        undo[Ply++] = new Undo(Move.None, -1, -1, Castling, EpSquare, HalfmoveClock, FullmoveNumber, Key, repetitionFloor);
        Key ^= EpKey() ^ Zobrist.Side;
        EpSquare = -1; Side ^= 1;
        // A search-only pass must never manufacture a repetition or rule-50 draw.
        repetitionFloor = Ply;
        history[Ply] = Key;
    }

    public void UnmakeMove()
    {
        if (Ply == 0) throw new InvalidOperationException("No move to undo.");
        Undo state = undo[--Ply];
        Side ^= 1;
        Move move = state.Move;
        if (move != Move.None)
        {
            int piece = Squares[move.To];
            Remove(piece, move.To);
            Put(move.Promotion == 0 ? piece : Side * 6, move.From);
            if (state.Captured >= 0) Put(state.Captured, state.CapturedSquare);
            if (move.IsCastle)
            {
                int rookFrom = move.To > move.From ? move.From + 3 : move.From - 4;
                int rookTo = move.To > move.From ? move.From + 1 : move.From - 1;
                Remove(Side * 6 + 3, rookTo); Put(Side * 6 + 3, rookFrom);
            }
        }
        Castling = state.Castling; EpSquare = state.Ep; HalfmoveClock = state.Halfmove;
        FullmoveNumber = state.Fullmove; Key = state.Key; repetitionFloor = state.RepetitionFloor;
    }
    private static int RightsMask(int square) => square switch
    { 4 => 12, 0 => 13, 7 => 14, 60 => 3, 56 => 7, 63 => 11, _ => 15 };

    public int GeneratePseudoLegal(Span<Move> moves, bool tacticalOnly = false)
    {
        int count = 0, us = Side, them = us ^ 1, offset = us * 6;
        ulong enemy = Colors[them] & ~Pieces[them * 6 + 5], occupied = Occupied;
        ulong pawns = Pieces[offset];
        int step = us == 0 ? 8 : -8, startRank = us == 0 ? 1 : 6, promotionRank = us == 0 ? 6 : 1;
        while (pawns != 0)
        {
            int from = Attacks.Pop(ref pawns), rank = from >> 3, to = from + step;
            if (Squares[to] < 0 && (!tacticalOnly || rank == promotionRank))
            {
                if (rank == promotionRank)
                    for (int promo = 1; promo <= 4; promo++) moves[count++] = new Move(from, to, promo);
                else
                {
                    moves[count++] = new Move(from, to);
                    if (rank == startRank && Squares[to + step] < 0) moves[count++] = new Move(from, to + step, 0, Move.DoublePush);
                }
            }
            ulong targets = Attacks.Pawn[us, from] & enemy;
            while (targets != 0)
            {
                to = Attacks.Pop(ref targets);
                if (rank == promotionRank)
                    for (int promo = 1; promo <= 4; promo++) moves[count++] = new Move(from, to, promo, Move.Capture);
                else moves[count++] = new Move(from, to, 0, Move.Capture);
            }
            if (EpSquare >= 0 && (Attacks.Pawn[us, from] & (1UL << EpSquare)) != 0)
                moves[count++] = new Move(from, EpSquare, 0, Move.EnPassant | Move.Capture);
        }
        for (int type = 1; type <= 5; type++)
        {
            ulong pieces = Pieces[offset + type];
            while (pieces != 0)
            {
                int from = Attacks.Pop(ref pieces);
                ulong targets = type switch
                {
                    1 => Attacks.Knight[from], 2 => Attacks.Bishop(from, occupied),
                    3 => Attacks.Rook(from, occupied), 4 => Attacks.Bishop(from, occupied) | Attacks.Rook(from, occupied),
                    _ => Attacks.King[from]
                };
                targets &= tacticalOnly ? enemy : ~(Colors[us] | Pieces[them * 6 + 5]);
                while (targets != 0)
                {
                    int to = Attacks.Pop(ref targets);
                    moves[count++] = new Move(from, to, 0, Squares[to] < 0 ? 0 : Move.Capture);
                }
            }
        }
        if (!tacticalOnly)
        {
            int king = us == 0 ? 4 : 60, kingRight = us == 0 ? 1 : 4, queenRight = us == 0 ? 2 : 8;
            ulong withoutKing = occupied & ~(1UL << king);
            if (Squares[king] == offset + 5 && !IsAttacked(king, them))
            {
                if ((Castling & kingRight) != 0 && Squares[king + 3] == offset + 3
                    && Squares[king + 1] < 0 && Squares[king + 2] < 0
                    && !IsAttacked(king + 1, them, withoutKing) && !IsAttacked(king + 2, them, withoutKing))
                    moves[count++] = new Move(king, king + 2, 0, Move.Castle);
                if ((Castling & queenRight) != 0 && Squares[king - 4] == offset + 3
                    && Squares[king - 1] < 0 && Squares[king - 2] < 0 && Squares[king - 3] < 0
                    && !IsAttacked(king - 1, them, withoutKing) && !IsAttacked(king - 2, them, withoutKing))
                    moves[count++] = new Move(king, king - 2, 0, Move.Castle);
            }
        }
        return count;
    }

    public int GenerateLegal(Span<Move> moves)
    {
        Span<Move> pseudo = stackalloc Move[256];
        int n = GeneratePseudoLegal(pseudo), count = 0;
        for (int i = 0; i < n; i++)
            if (TryMakeMove(pseudo[i])) { UnmakeMove(); moves[count++] = pseudo[i]; }
        return count;
    }
    public Move ParseMove(string uci)
    {
        Span<Move> moves = stackalloc Move[256];
        int count = GenerateLegal(moves);
        for (int i = 0; i < count; i++) if (moves[i].ToString() == uci) return moves[i];
        throw new FormatException($"Illegal move: {uci}");
    }

    public bool IsRepetition(int searchRootPly = int.MaxValue)
    {
        int matches = 0;
        int floor = Math.Max(repetitionFloor, Ply - HalfmoveClock);
        for (int i = Ply - 2; i >= floor; i -= 2)
            if (history[i] == Key && (++matches >= 2 || i >= searchRootPly)) return true;
        return false;
    }
    public bool HasPriorOccurrence()
    {
        int floor = Math.Max(repetitionFloor, Ply - HalfmoveClock);
        for (int i = Ply - 2; i >= floor; i -= 2) if (history[i] == Key) return true;
        return false;
    }
    public bool InsufficientMaterial()
    {
        if ((Pieces[0] | Pieces[6] | Pieces[3] | Pieces[9] | Pieces[4] | Pieces[10]) != 0) return false;
        ulong knights = Pieces[1] | Pieces[7], bishops = Pieces[2] | Pieces[8];
        if (BitOperations.PopCount(knights | bishops) <= 1) return true;
        const ulong dark = 0xAA55AA55AA55AA55;
        return knights == 0 && ((bishops & dark) == 0 || (bishops & ~dark) == 0);
    }

    public string ToFen()
    {
        var result = new StringBuilder();
        for (int rank = 7; rank >= 0; rank--)
        {
            int empty = 0;
            for (int file = 0; file < 8; file++)
            {
                int piece = Squares[rank * 8 + file];
                if (piece < 0) empty++;
                else { if (empty > 0) result.Append(empty); empty = 0; result.Append(PieceSymbols[piece]); }
            }
            if (empty > 0) result.Append(empty);
            if (rank > 0) result.Append('/');
        }
        string rights = "";
        if ((Castling & 1) != 0) rights += "K"; if ((Castling & 2) != 0) rights += "Q";
        if ((Castling & 4) != 0) rights += "k"; if ((Castling & 8) != 0) rights += "q";
        return $"{result} {(Side == 0 ? 'w' : 'b')} {(rights == "" ? "-" : rights)} {(EpSquare < 0 ? "-" : Move.SquareName(EpSquare))} {HalfmoveClock} {FullmoveNumber}";
    }
}
