using System.Globalization;
using System.Text;

namespace AgenticSupportGuide.Api.Parity;

/// <summary>
/// Python's string semantics where they differ from .NET's.
/// </summary>
/// <remarks>
/// Python measures and slices strings in code points; .NET in UTF-16 units.
/// A length limit or a truncation on text with an emoji in it would
/// otherwise land in a different place in each track. Python's <c>strip()</c>
/// also treats U+001C..U+001F as whitespace, which .NET does not.
/// </remarks>
public static class PyText
{
    /// <summary><c>len(text)</c>: code points, not UTF-16 units.</summary>
    public static int Len(string text)
    {
        var count = 0;
        for (var i = 0; i < text.Length; i++)
        {
            if (char.IsHighSurrogate(text[i]) && i + 1 < text.Length && char.IsLowSurrogate(text[i + 1]))
            {
                i++;
            }
            count++;
        }
        return count;
    }

    /// <summary><c>text[:count]</c>, by code points.</summary>
    public static string Head(string text, int count)
    {
        if (count <= 0)
        {
            return "";
        }
        var seen = 0;
        for (var i = 0; i < text.Length; i++)
        {
            if (seen == count)
            {
                return text[..i];
            }
            if (char.IsHighSurrogate(text[i]) && i + 1 < text.Length && char.IsLowSurrogate(text[i + 1]))
            {
                i++;
            }
            seen++;
        }
        return text;
    }

    /// <summary><c>str.isspace()</c> for one character.</summary>
    public static bool IsSpace(char c) => char.IsWhiteSpace(c) || c is >= '\u001c' and <= '\u001f';

    /// <summary><c>text.strip()</c>.</summary>
    public static string Strip(string text)
    {
        var start = 0;
        var end = text.Length;
        while (start < end && IsSpace(text[start]))
        {
            start++;
        }
        while (end > start && IsSpace(text[end - 1]))
        {
            end--;
        }
        return text[start..end];
    }

    /// <summary><c>text.rstrip()</c>.</summary>
    public static string RStrip(string text)
    {
        var end = text.Length;
        while (end > 0 && IsSpace(text[end - 1]))
        {
            end--;
        }
        return text[..end];
    }

    /// <summary><c>text.split()</c> with no separator: runs of whitespace.</summary>
    public static string[] Split(string text)
    {
        var parts = new List<string>();
        var current = new StringBuilder();
        foreach (var c in text)
        {
            if (IsSpace(c))
            {
                if (current.Length > 0)
                {
                    parts.Add(current.ToString());
                    current.Clear();
                }
            }
            else
            {
                current.Append(c);
            }
        }
        if (current.Length > 0)
        {
            parts.Add(current.ToString());
        }
        return [.. parts];
    }

    /// <summary><c>text.splitlines()</c>: Python's line boundaries, terminators dropped.</summary>
    public static string[] SplitLines(string text)
    {
        var lines = new List<string>();
        var start = 0;
        var i = 0;
        while (i < text.Length)
        {
            var c = text[i];
            if (c is '\n' or '\r' or '\v' or '\f' or '\u001c' or '\u001d' or '\u001e' or '\u0085' or '\u2028' or '\u2029')
            {
                lines.Add(text[start..i]);
                i += c == '\r' && i + 1 < text.Length && text[i + 1] == '\n' ? 2 : 1;
                start = i;
            }
            else
            {
                i++;
            }
        }
        if (start < text.Length)
        {
            lines.Add(text[start..]);
        }
        return [.. lines];
    }

    /// <summary><c>text.lower()</c>.</summary>
    public static string Lower(string text) => text.ToLowerInvariant();

    /// <summary><c>f"{n:0{width}d}"</c>.</summary>
    public static string ZeroPad(long n, int width) => n.ToString(new string('0', width), CultureInfo.InvariantCulture);

    /// <summary><c>repr(items)</c> for a list of strings: <c>['a', 'b']</c>.</summary>
    public static string ReprList(IEnumerable<string> items) => "[" + string.Join(", ", items.Select(Repr)) + "]";

    /// <summary><c>repr(text)</c>: single quotes unless the text holds one and no double quote.</summary>
    public static string Repr(string text)
    {
        var quote = text.Contains('\'') && !text.Contains('"') ? '"' : '\'';
        var sb = new StringBuilder();
        sb.Append(quote);
        foreach (var rune in text.EnumerateRunes())
        {
            var value = rune.Value;
            if (value == quote || value == '\\')
            {
                sb.Append('\\').Append((char)value);
            }
            else if (value == '\t')
            {
                sb.Append("\\t");
            }
            else if (value == '\n')
            {
                sb.Append("\\n");
            }
            else if (value == '\r')
            {
                sb.Append("\\r");
            }
            else if (!IsPrintable(rune))
            {
                sb.Append(value switch
                {
                    < 0x100 => "\\x" + value.ToString("x2", CultureInfo.InvariantCulture),
                    < 0x10000 => "\\u" + value.ToString("x4", CultureInfo.InvariantCulture),
                    _ => "\\U" + value.ToString("x8", CultureInfo.InvariantCulture),
                });
            }
            else
            {
                sb.Append(rune.ToString());
            }
        }
        sb.Append(quote);
        return sb.ToString();
    }

    // str.isprintable(): everything except the "Other" and "Separator"
    // categories, with the ASCII space allowed.
    private static bool IsPrintable(Rune rune)
    {
        if (rune.Value == ' ')
        {
            return true;
        }
        return Rune.GetUnicodeCategory(rune) switch
        {
            UnicodeCategory.Control or UnicodeCategory.Format or UnicodeCategory.Surrogate
                or UnicodeCategory.PrivateUse or UnicodeCategory.OtherNotAssigned
                or UnicodeCategory.LineSeparator or UnicodeCategory.ParagraphSeparator
                or UnicodeCategory.SpaceSeparator => false,
            _ => true,
        };
    }
}
