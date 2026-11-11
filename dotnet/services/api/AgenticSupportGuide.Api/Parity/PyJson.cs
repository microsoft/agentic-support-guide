using System.Globalization;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace AgenticSupportGuide.Api.Parity;

/// <summary>
/// Python's <c>json.dumps</c>, byte for byte.
/// </summary>
/// <remarks>
/// The agents' prompts embed JSON, and a prompt is part of the behaviour the
/// two tracks share: the same request must send the model the same text.
/// Python separates with <c>", "</c> and <c>": "</c>, escapes non-ASCII as
/// lowercase <c>\uXXXX</c>, and prints floats with <c>repr</c>.
/// </remarks>
public static class PyJson
{
    /// <summary>Serializer settings shared by the API responses and the prompts: snake_case, Python floats.</summary>
    public static JsonSerializerOptions SerializerOptions { get; } = CreateSerializerOptions();

    /// <summary>Apply the shared settings to an options instance (the API's own, for example).</summary>
    public static void Configure(JsonSerializerOptions options)
    {
        options.PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower;
        options.DictionaryKeyPolicy = null;
        options.DefaultIgnoreCondition = JsonIgnoreCondition.Never;
        options.Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping;
        if (!options.Converters.Any(c => c is PythonFloatConverter))
        {
            options.Converters.Add(new PythonFloatConverter());
        }
    }

    /// <summary><c>json.dumps(value)</c> for a .NET value, via the shared serializer settings.</summary>
    public static string Dumps(object? value, int? indent = null, bool ensureAscii = true, bool sortKeys = false)
    {
        var bytes = JsonSerializer.SerializeToUtf8Bytes(value, value?.GetType() ?? typeof(object), SerializerOptions);
        using var document = JsonDocument.Parse(bytes);
        return Dumps(document.RootElement, indent, ensureAscii, sortKeys);
    }

    /// <summary><c>json.dumps(value)</c> for parsed JSON. Numbers keep their source text.</summary>
    public static string Dumps(JsonElement value, int? indent = null, bool ensureAscii = true, bool sortKeys = false)
    {
        var sb = new StringBuilder();
        Write(sb, value, indent, 0, ensureAscii, sortKeys);
        return sb.ToString();
    }

    /// <summary>A JSON string literal as Python writes it.</summary>
    public static string Quote(string text, bool ensureAscii = true)
    {
        var sb = new StringBuilder(text.Length + 2);
        WriteString(sb, text, ensureAscii);
        return sb.ToString();
    }

    private static JsonSerializerOptions CreateSerializerOptions()
    {
        var options = new JsonSerializerOptions();
        Configure(options);
        options.MakeReadOnly(populateMissingResolver: true);
        return options;
    }

    private static void Write(StringBuilder sb, JsonElement value, int? indent, int level, bool ensureAscii, bool sortKeys)
    {
        switch (value.ValueKind)
        {
            case JsonValueKind.Object:
                var properties = value.EnumerateObject().ToList();
                if (sortKeys)
                {
                    properties.Sort((a, b) => string.CompareOrdinal(a.Name, b.Name));
                }
                if (properties.Count == 0)
                {
                    sb.Append("{}");
                    return;
                }
                sb.Append('{');
                for (var i = 0; i < properties.Count; i++)
                {
                    Separator(sb, i, indent, level + 1);
                    WriteString(sb, properties[i].Name, ensureAscii);
                    sb.Append(": ");
                    Write(sb, properties[i].Value, indent, level + 1, ensureAscii, sortKeys);
                }
                Close(sb, indent, level);
                sb.Append('}');
                return;
            case JsonValueKind.Array:
                var items = value.EnumerateArray().ToList();
                if (items.Count == 0)
                {
                    sb.Append("[]");
                    return;
                }
                sb.Append('[');
                for (var i = 0; i < items.Count; i++)
                {
                    Separator(sb, i, indent, level + 1);
                    Write(sb, items[i], indent, level + 1, ensureAscii, sortKeys);
                }
                Close(sb, indent, level);
                sb.Append(']');
                return;
            case JsonValueKind.String:
                WriteString(sb, value.GetString()!, ensureAscii);
                return;
            case JsonValueKind.Number:
                sb.Append(value.GetRawText());
                return;
            case JsonValueKind.True:
                sb.Append("true");
                return;
            case JsonValueKind.False:
                sb.Append("false");
                return;
            default:
                sb.Append("null");
                return;
        }
    }

    private static void Separator(StringBuilder sb, int index, int? indent, int level)
    {
        if (indent is null)
        {
            if (index > 0)
            {
                sb.Append(", ");
            }
            return;
        }
        if (index > 0)
        {
            sb.Append(',');
        }
        sb.Append('\n').Append(' ', indent.Value * level);
    }

    private static void Close(StringBuilder sb, int? indent, int level)
    {
        if (indent is not null)
        {
            sb.Append('\n').Append(' ', indent.Value * level);
        }
    }

    private static void WriteString(StringBuilder sb, string text, bool ensureAscii)
    {
        sb.Append('"');
        foreach (var c in text)
        {
            switch (c)
            {
                case '"':
                    sb.Append("\\\"");
                    break;
                case '\\':
                    sb.Append("\\\\");
                    break;
                case '\n':
                    sb.Append("\\n");
                    break;
                case '\r':
                    sb.Append("\\r");
                    break;
                case '\t':
                    sb.Append("\\t");
                    break;
                case '\b':
                    sb.Append("\\b");
                    break;
                case '\f':
                    sb.Append("\\f");
                    break;
                default:
                    // UTF-16 units map one to one onto Python's escapes,
                    // including the surrogate pair for a character above U+FFFF.
                    if (c < ' ' || (ensureAscii && c > '~'))
                    {
                        sb.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                    }
                    else
                    {
                        sb.Append(c);
                    }
                    break;
            }
        }
        sb.Append('"');
    }

    /// <summary>Writes a double the way Python prints a float: <c>72.0</c>, not <c>72</c>.</summary>
    public sealed class PythonFloatConverter : JsonConverter<double>
    {
        /// <inheritdoc />
        public override double Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options) => reader.GetDouble();

        /// <inheritdoc />
        public override void Write(Utf8JsonWriter writer, double value, JsonSerializerOptions options) =>
            writer.WriteRawValue(PyFloat.Repr(value), skipInputValidation: true);
    }
}
