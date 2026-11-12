using System.Globalization;
using System.Numerics;
using System.Text;

namespace AgenticSupportGuide.Api.Parity;

/// <summary>
/// Python's float arithmetic where it differs from .NET's: <c>round</c>,
/// <c>repr</c>, <c>f"{x:.1f}"</c> and <c>sum</c>.
/// </summary>
/// <remarks>
/// Both tracks must produce the same numbers and the same text from the same
/// data. Python rounds the exact binary value half-to-even, prints the
/// shortest repr with a trailing <c>.0</c>, and sums floats with Neumaier
/// compensation; .NET's defaults differ in each, by a last digit at a time.
/// </remarks>
public static class PyFloat
{
    // CPython's NDIGITS_MAX / NDIGITS_MIN for float.__round__.
    private const int NDigitsMax = 323;
    private const int NDigitsMin = -308;

    /// <summary><c>round(x, ndigits)</c>.</summary>
    public static double Round(double x, int ndigits)
    {
        if (!double.IsFinite(x) || x == 0 || ndigits > NDigitsMax)
        {
            return x;
        }
        if (ndigits < NDigitsMin)
        {
            return 0.0 * x;
        }
        var (negative, digits) = RoundedScaled(x, ndigits);
        var text = (negative ? "-" : "") + digits.ToString(CultureInfo.InvariantCulture) + "e" + (-ndigits).ToString(CultureInfo.InvariantCulture);
        return double.Parse(text, NumberStyles.Float, CultureInfo.InvariantCulture);
    }

    /// <summary><c>round(x)</c>: the nearest integer, ties to even.</summary>
    public static long RoundToInt(double x) => (long)Math.Round(x, MidpointRounding.ToEven);

    /// <summary><c>f"{x:.{digits}f}"</c>.</summary>
    public static string Fixed(double x, int digits)
    {
        if (double.IsNaN(x))
        {
            return "nan";
        }
        if (double.IsInfinity(x))
        {
            return x > 0 ? "inf" : "-inf";
        }
        var (negative, scaled) = x == 0 ? (double.IsNegative(x), BigInteger.Zero) : RoundedScaled(x, digits);
        var text = scaled.ToString(CultureInfo.InvariantCulture);
        if (digits > 0)
        {
            text = text.PadLeft(digits + 1, '0');
            text = text[..^digits] + "." + text[^digits..];
        }
        return (negative ? "-" : "") + text;
    }

    /// <summary><c>repr(x)</c>: shortest round-trip digits, Python's layout.</summary>
    public static string Repr(double x)
    {
        if (double.IsNaN(x))
        {
            return "NaN";
        }
        if (double.IsInfinity(x))
        {
            return x > 0 ? "Infinity" : "-Infinity";
        }
        if (x == 0)
        {
            return double.IsNegative(x) ? "-0.0" : "0.0";
        }

        // .NET's "R" is the same shortest round-trip digit string; only the
        // layout differs, so take the digits and the exponent and re-lay them.
        var shortest = x.ToString("R", CultureInfo.InvariantCulture);
        var negative = shortest.StartsWith('-');
        var (digitString, pointPosition) = Decompose(negative ? shortest[1..] : shortest);

        var sb = new StringBuilder();
        if (negative)
        {
            sb.Append('-');
        }
        // Python's repr switches to exponent form outside 1e-4 <= |x| < 1e16.
        if (pointPosition <= -4 || pointPosition > 16)
        {
            sb.Append(digitString[0]);
            if (digitString.Length > 1)
            {
                sb.Append('.').Append(digitString, 1, digitString.Length - 1);
            }
            var exponent = pointPosition - 1;
            sb.Append('e').Append(exponent < 0 ? '-' : '+');
            sb.Append(Math.Abs(exponent).ToString("00", CultureInfo.InvariantCulture));
        }
        else if (pointPosition <= 0)
        {
            sb.Append("0.").Append('0', -pointPosition).Append(digitString);
        }
        else if (pointPosition >= digitString.Length)
        {
            sb.Append(digitString).Append('0', pointPosition - digitString.Length).Append(".0");
        }
        else
        {
            sb.Append(digitString, 0, pointPosition).Append('.').Append(digitString, pointPosition, digitString.Length - pointPosition);
        }
        return sb.ToString();
    }

    /// <summary><c>sum(values)</c> over floats: Neumaier-compensated, as CPython 3.12+ does.</summary>
    public static double Sum(IEnumerable<double> values)
    {
        using var e = values.GetEnumerator();
        if (!e.MoveNext())
        {
            return 0;
        }
        // sum() starts from the integer 0, so the first float becomes the total.
        var total = 0 + e.Current;
        var compensation = 0.0;
        while (e.MoveNext())
        {
            var x = e.Current;
            var t = total + x;
            if (Math.Abs(total) >= Math.Abs(x))
            {
                compensation += (total - t) + x;
            }
            else
            {
                compensation += (x - t) + total;
            }
            total = t;
        }
        if (compensation != 0 && double.IsFinite(compensation))
        {
            total += compensation;
        }
        return total;
    }

    /// <summary><c>sum(values) / len(values)</c>.</summary>
    public static double Mean(IReadOnlyCollection<double> values) => Sum(values) / values.Count;

    // |x| * 10^digits rounded half-to-even on the exact binary value.
    private static (bool Negative, BigInteger Scaled) RoundedScaled(double x, int digits)
    {
        var negative = double.IsNegative(x);
        var bits = BitConverter.DoubleToInt64Bits(Math.Abs(x));
        var exponent = (int)((bits >> 52) & 0x7FF);
        var mantissa = bits & 0xFFFFFFFFFFFFFL;
        if (exponent == 0)
        {
            exponent = 1;
        }
        else
        {
            mantissa |= 1L << 52;
        }
        exponent -= 1075;

        BigInteger numerator = mantissa;
        var denominator = BigInteger.One;
        if (exponent > 0)
        {
            numerator <<= exponent;
        }
        else
        {
            denominator <<= -exponent;
        }
        if (digits >= 0)
        {
            numerator *= BigInteger.Pow(10, digits);
        }
        else
        {
            denominator *= BigInteger.Pow(10, -digits);
        }

        var quotient = BigInteger.DivRem(numerator, denominator, out var remainder);
        var comparison = (remainder * 2).CompareTo(denominator);
        if (comparison > 0 || (comparison == 0 && !quotient.IsEven))
        {
            quotient += 1;
        }
        return (negative, quotient);
    }

    // "1.25E-05" / "123.45" / "1E+16" -> ("125", -4) meaning 0.125 * 10^-4.
    private static (string Digits, int PointPosition) Decompose(string text)
    {
        var exponent = 0;
        var e = text.IndexOfAny(['E', 'e']);
        if (e >= 0)
        {
            exponent = int.Parse(text[(e + 1)..], NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture);
            text = text[..e];
        }
        var dot = text.IndexOf('.');
        var integerPart = dot >= 0 ? text[..dot] : text;
        var fraction = dot >= 0 ? text[(dot + 1)..] : "";
        var digits = integerPart + fraction;
        var point = integerPart.Length + exponent;

        var leading = 0;
        while (leading < digits.Length - 1 && digits[leading] == '0')
        {
            leading++;
        }
        digits = digits[leading..];
        point -= leading;
        digits = digits.TrimEnd('0');
        return (digits.Length == 0 ? "0" : digits, point);
    }
}
