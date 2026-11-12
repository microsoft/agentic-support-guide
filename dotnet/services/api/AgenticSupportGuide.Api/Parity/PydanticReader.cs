using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace AgenticSupportGuide.Api.Parity;

/// <summary>
/// Reads the fields of one JSON object the way Pydantic validates parsed JSON,
/// recording a dotted error path for every field that fails.
/// </summary>
/// <remarks>
/// Both tracks must accept and reject the same request bodies and the same
/// model outputs. Pydantic's lax mode is the rule: an integer field accepts
/// <c>28</c>, <c>28.0</c>, <c>true</c> and <c>"28"</c>; a string field
/// accepts only a string; unknown fields are ignored; a list over its length
/// limit is reported on its own without its items.
/// </remarks>
public sealed class PydanticReader
{
    private static readonly HashSet<string> TrueWords = ["1", "on", "t", "true", "y", "yes"];
    private static readonly HashSet<string> FalseWords = ["0", "off", "f", "false", "n", "no"];

    private readonly JsonElement _obj;
    private readonly string _location;
    private readonly List<string> _errors;
    private readonly int _errorsAtStart;

    public PydanticReader(JsonElement obj, string location, List<string> errors)
    {
        _obj = obj;
        _location = location;
        _errors = errors;
        _errorsAtStart = errors.Count;
    }

    /// <summary>True once any field read through this reader (or a nested one) has failed.</summary>
    public bool Failed => _errors.Count > _errorsAtStart;

    /// <summary>A constraint on a string, as Pydantic's <c>StringConstraints</c>.</summary>
    public sealed record StrRule(int? MinLength = null, int? MaxLength = null, Regex? Pattern = null);

    public string? Str(string name, int? minLength = null, int? maxLength = null, Regex? pattern = null, string? defaultValue = null)
    {
        if (!TryGet(name, out var value))
        {
            if (defaultValue is null)
            {
                _errors.Add(At(name));
            }
            return defaultValue;
        }
        return CheckStr(value, At(name), new StrRule(minLength, maxLength, pattern));
    }

    /// <summary><c>str | None</c>, defaulting to None.</summary>
    public string? OptionalStr(string name, int? maxLength = null)
    {
        if (!TryGet(name, out var value) || value.ValueKind == JsonValueKind.Null)
        {
            return null;
        }
        return CheckStr(value, At(name), new StrRule(MaxLength: maxLength));
    }

    /// <summary>A string that must be one of <paramref name="allowed"/> (a Literal or a StrEnum).</summary>
    public string? OneOf(string name, IReadOnlyCollection<string> allowed, string? defaultValue = null)
    {
        if (!TryGet(name, out var value))
        {
            if (defaultValue is null)
            {
                _errors.Add(At(name));
            }
            return defaultValue;
        }
        if (value.ValueKind != JsonValueKind.String || !allowed.Contains(value.GetString()!))
        {
            _errors.Add(At(name));
            return null;
        }
        return value.GetString();
    }

    public int? Int(string name, long min = long.MinValue, long max = long.MaxValue, int? defaultValue = null)
    {
        var path = At(name);
        if (!TryGet(name, out var value))
        {
            if (defaultValue is null)
            {
                _errors.Add(path);
            }
            return defaultValue;
        }
        if (LaxInt(value) is not { } number || number < min || number > max)
        {
            _errors.Add(path);
            return null;
        }
        return (int)number;
    }

    public double? Float(string name, double min = double.NegativeInfinity, double max = double.PositiveInfinity)
    {
        var path = At(name);
        if (!TryGet(name, out var value))
        {
            _errors.Add(path);
            return null;
        }
        // NaN fails both bounds checks in Pydantic, as it does here.
        if (LaxFloat(value) is not { } number || (!double.IsNegativeInfinity(min) && !(number >= min)) || (!double.IsPositiveInfinity(max) && !(number <= max)))
        {
            _errors.Add(path);
            return null;
        }
        return number;
    }

    public bool? Bool(string name)
    {
        var path = At(name);
        if (!TryGet(name, out var value))
        {
            _errors.Add(path);
            return null;
        }
        if (LaxBool(value) is not { } flag)
        {
            _errors.Add(path);
            return null;
        }
        return flag;
    }

    /// <summary><c>list[str]</c>, each item checked against <paramref name="item"/>.</summary>
    public List<string>? StrList(string name, int maxItems, StrRule? item = null, bool required = true)
    {
        var path = At(name);
        if (!TryGet(name, out var value))
        {
            if (required)
            {
                _errors.Add(path);
                return null;
            }
            return [];
        }
        return CheckStrList(value, path, maxItems, item);
    }

    public T? Model<T>(string name, Func<PydanticReader, T?> parse)
        where T : class
    {
        var path = At(name);
        if (!TryGet(name, out var value))
        {
            _errors.Add(path);
            return null;
        }
        if (value.ValueKind != JsonValueKind.Object)
        {
            _errors.Add(path);
            return null;
        }
        return parse(new PydanticReader(value, path, _errors));
    }

    public List<T>? ModelList<T>(string name, Func<PydanticReader, T?> parse, int maxItems, bool required = true)
        where T : class
    {
        var path = At(name);
        if (!TryGet(name, out var value))
        {
            if (required)
            {
                _errors.Add(path);
                return null;
            }
            return [];
        }
        if (value.ValueKind != JsonValueKind.Array)
        {
            _errors.Add(path);
            return null;
        }
        // Too long is reported on its own; the items are not examined.
        if (value.GetArrayLength() > maxItems)
        {
            _errors.Add(path);
            return null;
        }
        var items = new List<T>();
        var index = 0;
        foreach (var element in value.EnumerateArray())
        {
            var itemPath = $"{path}.{index++}";
            if (element.ValueKind != JsonValueKind.Object)
            {
                _errors.Add(itemPath);
                continue;
            }
            if (parse(new PydanticReader(element, itemPath, _errors)) is { } parsed)
            {
                items.Add(parsed);
            }
        }
        return items;
    }

    /// <summary><c>dict[str, bool | list[str]]</c>: each value a bool or a list of strings.</summary>
    public Dictionary<string, object>? BoolOrStrListMap(string name)
    {
        var path = At(name);
        if (!TryGet(name, out var value))
        {
            _errors.Add(path);
            return null;
        }
        if (value.ValueKind != JsonValueKind.Object)
        {
            _errors.Add(path);
            return null;
        }
        var result = new Dictionary<string, object>();
        foreach (var property in LastProperties(value))
        {
            var entryPath = $"{path}.{property.Name}";
            if (LaxBool(property.Value) is { } flag)
            {
                result[property.Name] = flag;
                continue;
            }
            if (property.Value.ValueKind == JsonValueKind.Array)
            {
                var before = _errors.Count;
                var list = CheckStrList(property.Value, $"{entryPath}.list[str]", int.MaxValue, null);
                if (_errors.Count == before && list is not null)
                {
                    result[property.Name] = list;
                    continue;
                }
                _errors.Insert(before, $"{entryPath}.bool");
                continue;
            }
            // Neither member of the union accepted it; Pydantic reports both.
            _errors.Add($"{entryPath}.bool");
            _errors.Add($"{entryPath}.list[str]");
        }
        return result;
    }

    private string At(string name) => _location.Length == 0 ? name : $"{_location}.{name}";

    private string? CheckStr(JsonElement value, string path, StrRule? rule)
    {
        if (value.ValueKind != JsonValueKind.String)
        {
            _errors.Add(path);
            return null;
        }
        var text = value.GetString()!;
        if (rule is not null)
        {
            var length = PyText.Len(text);
            if ((rule.MinLength is { } min && length < min) || (rule.MaxLength is { } max && length > max) || (rule.Pattern is not null && !rule.Pattern.IsMatch(text)))
            {
                _errors.Add(path);
                return null;
            }
        }
        return text;
    }

    private List<string>? CheckStrList(JsonElement value, string path, int maxItems, StrRule? item)
    {
        if (value.ValueKind != JsonValueKind.Array)
        {
            _errors.Add(path);
            return null;
        }
        if (value.GetArrayLength() > maxItems)
        {
            _errors.Add(path);
            return null;
        }
        var items = new List<string>();
        var index = 0;
        foreach (var element in value.EnumerateArray())
        {
            if (CheckStr(element, $"{path}.{index}", item) is { } text)
            {
                items.Add(text);
            }
            index++;
        }
        return items;
    }

    private bool TryGet(string name, out JsonElement value)
    {
        // A repeated key keeps its last value, as a Python dict does.
        var found = false;
        value = default;
        foreach (var property in _obj.EnumerateObject())
        {
            if (property.NameEquals(name))
            {
                value = property.Value;
                found = true;
            }
        }
        return found;
    }

    private static IEnumerable<JsonProperty> LastProperties(JsonElement value)
    {
        var last = new Dictionary<string, JsonProperty>(StringComparer.Ordinal);
        var order = new List<string>();
        foreach (var property in value.EnumerateObject())
        {
            if (!last.ContainsKey(property.Name))
            {
                order.Add(property.Name);
            }
            last[property.Name] = property;
        }
        return order.Select(name => last[name]);
    }

    // int: an integer, a float with no fractional part, a bool, or a string
    // holding one of those.
    private static long? LaxInt(JsonElement value)
    {
        switch (value.ValueKind)
        {
            case JsonValueKind.True:
                return 1;
            case JsonValueKind.False:
                return 0;
            case JsonValueKind.Number:
                if (value.TryGetInt64(out var whole))
                {
                    return whole;
                }
                var d = value.GetDouble();
                if (double.IsFinite(d) && Math.Floor(d) == d)
                {
                    return d >= long.MaxValue ? long.MaxValue : d <= long.MinValue ? long.MinValue : (long)d;
                }
                return null;
            case JsonValueKind.String:
                var text = PyText.Strip(value.GetString()!);
                var dot = text.IndexOf('.');
                if (dot >= 0 && text[(dot + 1)..].All(c => c == '0'))
                {
                    text = text[..dot];
                }
                return long.TryParse(text, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out var parsed) ? parsed : null;
            default:
                return null;
        }
    }

    // float: a number, a bool, or a string holding a number.
    private static double? LaxFloat(JsonElement value)
    {
        switch (value.ValueKind)
        {
            case JsonValueKind.True:
                return 1.0;
            case JsonValueKind.False:
                return 0.0;
            case JsonValueKind.Number:
                return value.GetDouble();
            case JsonValueKind.String:
                var text = PyText.Strip(value.GetString()!).ToLowerInvariant();
                switch (text)
                {
                    case "nan" or "+nan" or "-nan":
                        return double.NaN;
                    case "inf" or "+inf" or "infinity" or "+infinity":
                        return double.PositiveInfinity;
                    case "-inf" or "-infinity":
                        return double.NegativeInfinity;
                }
                return double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out var parsed) ? parsed : null;
            default:
                return null;
        }
    }

    // bool: true/false, 0/1, 0.0/1.0, or one of Pydantic's words.
    private static bool? LaxBool(JsonElement value)
    {
        switch (value.ValueKind)
        {
            case JsonValueKind.True:
                return true;
            case JsonValueKind.False:
                return false;
            case JsonValueKind.Number:
                var d = value.GetDouble();
                return d == 1 ? true : d == 0 ? false : null;
            case JsonValueKind.String:
                var text = value.GetString()!.ToLowerInvariant();
                return TrueWords.Contains(text) ? true : FalseWords.Contains(text) ? false : null;
            default:
                return null;
        }
    }
}
