namespace AgenticSupportGuide.Api.Parity;

/// <summary>
/// Python's <c>random.Random</c>: the same Mersenne Twister, seeded the same
/// way, drawing the same numbers.
/// </summary>
/// <remarks>
/// The synthetic data is generated from a fixed seed, and both tracks must
/// generate the same data: a workshop step that says "DLR-0042 scores 61.3"
/// has to be true in either language. Only the methods the app uses are here.
/// </remarks>
public sealed class PyRandom
{
    private const int N = 624;
    private const int M = 397;
    private const uint MatrixA = 0x9908b0dfU;
    private const uint UpperMask = 0x80000000U;
    private const uint LowerMask = 0x7fffffffU;

    private readonly uint[] _mt = new uint[N];
    private int _mti = N + 1;

    /// <summary><c>random.Random(seed)</c> for an integer seed.</summary>
    public PyRandom(long seed)
    {
        // CPython splits abs(seed) into 32-bit words, least significant first.
        var n = (ulong)Math.Abs(seed);
        var key = new List<uint>();
        do
        {
            key.Add((uint)(n & 0xffffffffUL));
            n >>= 32;
        }
        while (n != 0);
        InitByArray([.. key]);
    }

    /// <summary><c>random()</c>: a float in [0.0, 1.0) with 53 random bits.</summary>
    public double Random()
    {
        var a = GenRandUInt32() >> 5;
        var b = GenRandUInt32() >> 6;
        return ((a * 67108864.0) + b) * (1.0 / 9007199254740992.0);
    }

    /// <summary><c>uniform(a, b)</c>.</summary>
    public double Uniform(double a, double b) => a + ((b - a) * Random());

    /// <summary><c>randrange(stop)</c>.</summary>
    public int RandRange(int stop)
    {
        if (stop <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(stop), "empty range for randrange()");
        }
        return (int)RandBelow((ulong)stop);
    }

    /// <summary><c>randrange(start, stop)</c>.</summary>
    public int RandRange(int start, int stop)
    {
        var width = (long)stop - start;
        if (width <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(stop), "empty range for randrange()");
        }
        return (int)(start + (long)RandBelow((ulong)width));
    }

    /// <summary><c>randint(a, b)</c>: inclusive of both ends.</summary>
    public int RandInt(int a, int b) => RandRange(a, b + 1);

    /// <summary><c>choice(seq)</c>.</summary>
    public T Choice<T>(IReadOnlyList<T> items) => items[(int)RandBelow((ulong)items.Count)];

    /// <summary><c>shuffle(x)</c>, in place.</summary>
    public void Shuffle<T>(IList<T> items)
    {
        for (var i = items.Count - 1; i > 0; i--)
        {
            var j = (int)RandBelow((ulong)(i + 1));
            (items[i], items[j]) = (items[j], items[i]);
        }
    }

    /// <summary><c>getrandbits(k)</c> for k up to 64.</summary>
    public ulong GetRandBits(int k)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(k);
        ArgumentOutOfRangeException.ThrowIfGreaterThan(k, 64);
        if (k == 0)
        {
            return 0;
        }
        if (k <= 32)
        {
            return GenRandUInt32() >> (32 - k);
        }
        // Wider values are filled one 32-bit word at a time, low word first.
        var low = (ulong)GenRandUInt32();
        var high = (ulong)(GenRandUInt32() >> (64 - k));
        return low | (high << 32);
    }

    // `_randbelow_with_getrandbits`: rejection sampling, never modulo.
    private ulong RandBelow(ulong n)
    {
        var k = 64 - System.Numerics.BitOperations.LeadingZeroCount(n);
        var r = GetRandBits(k);
        while (r >= n)
        {
            r = GetRandBits(k);
        }
        return r;
    }

    private void InitGenRand(uint s)
    {
        _mt[0] = s;
        for (_mti = 1; _mti < N; _mti++)
        {
            _mt[_mti] = (1812433253U * (_mt[_mti - 1] ^ (_mt[_mti - 1] >> 30))) + (uint)_mti;
        }
    }

    private void InitByArray(uint[] key)
    {
        InitGenRand(19650218U);
        int i = 1, j = 0;
        for (var k = Math.Max(N, key.Length); k > 0; k--)
        {
            _mt[i] = (_mt[i] ^ ((_mt[i - 1] ^ (_mt[i - 1] >> 30)) * 1664525U)) + key[j] + (uint)j;
            i++;
            j++;
            if (i >= N)
            {
                _mt[0] = _mt[N - 1];
                i = 1;
            }
            if (j >= key.Length)
            {
                j = 0;
            }
        }
        for (var k = N - 1; k > 0; k--)
        {
            _mt[i] = (_mt[i] ^ ((_mt[i - 1] ^ (_mt[i - 1] >> 30)) * 1566083941U)) - (uint)i;
            i++;
            if (i >= N)
            {
                _mt[0] = _mt[N - 1];
                i = 1;
            }
        }
        _mt[0] = 0x80000000U;
    }

    private uint GenRandUInt32()
    {
        uint y;
        if (_mti >= N)
        {
            int kk;
            for (kk = 0; kk < N - M; kk++)
            {
                y = (_mt[kk] & UpperMask) | (_mt[kk + 1] & LowerMask);
                _mt[kk] = _mt[kk + M] ^ (y >> 1) ^ ((y & 1U) != 0 ? MatrixA : 0U);
            }
            for (; kk < N - 1; kk++)
            {
                y = (_mt[kk] & UpperMask) | (_mt[kk + 1] & LowerMask);
                _mt[kk] = _mt[kk + (M - N)] ^ (y >> 1) ^ ((y & 1U) != 0 ? MatrixA : 0U);
            }
            y = (_mt[N - 1] & UpperMask) | (_mt[0] & LowerMask);
            _mt[N - 1] = _mt[M - 1] ^ (y >> 1) ^ ((y & 1U) != 0 ? MatrixA : 0U);
            _mti = 0;
        }

        y = _mt[_mti++];
        y ^= y >> 11;
        y ^= (y << 7) & 0x9d2c5680U;
        y ^= (y << 15) & 0xefc60000U;
        y ^= y >> 18;
        return y;
    }
}
