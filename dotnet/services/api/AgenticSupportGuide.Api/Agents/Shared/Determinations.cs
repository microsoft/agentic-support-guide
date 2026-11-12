using System.Collections;
using System.Text.RegularExpressions;

namespace AgenticSupportGuide.Api.Agents.Shared;

/// <summary>
/// Forbidden-determination policy.
/// </summary>
/// <remarks>
/// One definition enforced in three places: the validator agent, the hosted
/// agent's output gate, and the prompt envelope every model receives. Each of
/// those used to carry its own phrase list and they had already drifted apart.
///
/// This is a denylist, and denylists leak — Module 8 measures exactly that.
/// What this type owes the rest of the system is that it fails *closed*: an
/// exemption has to be earned by a construction sitting immediately next to
/// the match, never by a keyword loose in the surrounding text.
///
/// The patterns are the Python track's, with Python's definitions of a word
/// character, a word boundary and whitespace spelled out, so both tracks give
/// the same verdict on the same text.
/// </remarks>
public static class Determinations
{
    // Prose injected into prompts and caveats. Tests hold this in sync with the
    // patterns below so the instruction and the detector cannot disagree.
    public const string PolicyNounPhrase =
        "pricing, financing, credit, compliance, safety, or individual staffing determinations";

    // The phrase the validator requires to appear in a draft's caveats. The
    // caveat below has to contain it: the two rules used to live in different
    // files and the standard caveat did not satisfy the standard check.
    public const string RequiredReviewPhrase = "human review";

    public const string HumanReviewCaveat =
        "A human must review this before acting on it. This is synthetic guidance " +
        "and is not a pricing, financing, credit, compliance, safety, or staffing " +
        "determination. Human review is required before use.";

    // Python's \w (str.isalnum() or "_"), \b and \s (str.isspace()).
    private const string W = @"[\p{L}\p{N}_]";
    private const string B = @"(?:(?<=[\p{L}\p{N}_])(?![\p{L}\p{N}_])|(?<![\p{L}\p{N}_])(?=[\p{L}\p{N}_]))";
    private const string S = @"[\s\x1c-\x1f]";

    // Inside a character class, \s spelled the same way.
    private const string SIn = @"\s\x1c-\x1f";

    private const RegexOptions Options = RegexOptions.IgnoreCase | RegexOptions.CultureInvariant;

    // The categories named in PolicyNounPhrase, so the instruction the models
    // are given and the rule enforced here cover the same ground.
    private const string Categories = "pricing|price|financing|finance|credit|lending|compliance|legal|safety|staffing";

    // `Disclaimable` says whether "this is not a X" is a legitimate disclaimer.
    // It is, for the *act* ("this is not a credit decision"). It is not for the
    // *ruling*: "this vehicle has no open recalls" is a safety claim whichever
    // way it is phrased, and negating it does not make it safe to assert.
    private static readonly (Regex Pattern, bool Disclaimable)[] Rules =
    [
        (Rx($@"{B}(?:{Categories}){S}+determinations?{B}"), true),
        // Committing money.
        (Rx($@"{B}(?:guarantee|guarantees|guaranteed){S}+(?:a{S}+|the{S}+)?(?:price|discount|rate|apr|trade[-{SIn}]?in){B}"), true),
        (Rx($@"{B}trade[-{SIn}]?in{S}+is{S}+worth{B}"), false),
        (Rx($@"{B}(?:final|best|lowest){S}+price{S}+(?:is|will{S}+be){B}"), false),
        (Rx($@"{B}(?:discount|reduction){S}+of{S}+\$"), false),
        (Rx($@"{B}we{S}+(?:will|can){S}+(?:sell|offer|match|beat){B}[^.!?;]{{0,40}}\$"), false),
        // Credit and financing decisions.
        (Rx($@"{B}(?:approved|pre[-{SIn}]?approved|declined|denied){S}+for{S}+(?:financing|finance|credit|a{S}+loan){B}"), false),
        (Rx($@"{B}qualif(?:y|ies|ied){S}+for{S}+(?:financing|credit){B}"), false),
        (Rx($@"{B}credit{S}+(?:decision|approval|denial){B}"), true),
        // Judging a named individual rather than the process.
        (Rx($@"{B}(?:should{S}+be{S}+)?(?:terminated|dismissed|fired|put{S}+on{S}+a{S}+performance{S}+plan|disciplined){B}"), true),
        (Rx($@"{B}(?:poor|bad|weak|underperforming|incompetent){S}+(?:salesperson|sales{S}+person|advisor|adviser|employee|manager){B}"), false),
        // Compliance claims.
        (Rx($@"{B}(?:is|are){S}+(?:fully{S}+)?compliant{S}+with{B}"), true),
        (Rx($@"{B}compl(?:y|ies|ied){S}+with{B}[^.!?;]{{0,40}}{B}(?:regulation|regulations|rule|rules|law|laws|ftc|advertising){B}"), true),
        // Safety and recall claims.
        (Rx($@"{B}no{S}+open{S}+recalls?{B}"), false),
        (Rx($@"{B}recall[-{SIn}]free{B}"), false),
        (Rx($@"{B}safe{S}+to{S}+drive{B}"), false),
        (Rx($@"{B}passed{S}+(?:the{S}+)?(?:safety{S}+|roadworthiness{S}+)?inspection{B}"), false),
        // Guaranteeing a commercial outcome.
        (Rx($@"{B}(?:will|shall){S}+(?:increase|grow|improve|lift|boost){B}[^.!?;]{{0,20}}{B}sales{B}"), false),
        (Rx($@"{B}you{S}+will{S}+sell{B}"), false),
        (Rx($@"{B}guaranteed{S}+to{S}+{W}+"), true),
    ];

    // Every exemption is anchored with `$` against the text immediately
    // preceding the match. That anchoring is what replaced sentence splitting:
    // a cue two sentences away, across a newline, or after an abbreviation like
    // "Dr." can no longer reach the match, and no window length has to be guessed.
    private static readonly Regex Disclaimer = Rx(
        $@"(?:{B}(?:is|are|was|were|am){S}+not{S}+(?:a|an|the)?{S}*"
        + $@"|{B}(?:isn't|aren't|wasn't|weren't){S}+(?:a|an|the)?{S}*"
        // A disclaimer may list the categories it denies, as the caveat itself
        // does: "is not a pricing, financing, credit, compliance, safety,
        // determination". Without this the caveat flags its own policy.
        + $@"|{B}(?:is|are|was|were|am){S}+not{S}+(?:a|an|the){S}+(?:[a-z]+,{S}*)+(?:or{S}+)?"
        + $@"|{B}not{S}+(?:a|an|the){S}*"
        + $@"|{B}no{S}+"
        + $@"|{B}never{S}+(?:a|an|the)?{S}*"
        + $@"|{B}(?:cannot|can't|do{S}+not|don't|does{S}+not|doesn't|must{S}+not){S}+"
        + $@"(?:make|provide|offer|give|issue|constitute){S}+(?:a|an|the)?{S}*"
        + ")$");

    // Deferral to a human decision-maker, e.g. "a qualified inspector may
    // determine". `will` is deliberately absent: it predicts rather than
    // defers. The role list is a deliberate superset; an unmatched role simply
    // never grants an exemption.
    private static readonly Regex DeferralBefore = Rx(
        $@"{B}(?:a|an|the)?{S}*(?:qualified|licensed|certified|independent|trained)?{S}*"
        + "(?:clinician|specialist|professional|psychologist|physician|doctor|"
        + $@"evaluator|assessor|inspector|reviewer|expert)s?{S}+"
        + $@"(?:may|might|can|could|would|should){S}+$");

    // "A credit decision must be left to the finance office." - the deferral follows.
    private static readonly Regex DeferralAfter = Rx(
        $@"^{S}*(?:must|should|can|could|may|has{S}+to){S}+(?:only{S}+)?be{S}+"
        + $@"(?:left|made|given|provided|determined|decided){S}+(?:to|by){B}");

    // A claim that human review can be skipped is itself a determination: it
    // revokes the one control every answer depends on.
    //
    // Two kinds. A *soft* denial names an action ("skip human review") and can
    // be legitimate under a prohibition: "do not skip human review" requires
    // review. A *hard* denial states the conclusion ("human review is
    // optional"), and no preceding word rescues that.
    private static readonly Regex ReviewSkipAction = Rx(
        $@"{B}(?:no|without|skip(?:s|ped|ping)?|bypass(?:es|ed|ing)?|waive[sd]?|"
        + $@"forgo(?:es|ing)?|omit(?:s|ted|ting)?|disregard(?:s|ed|ing)?|ignore[sd]?){B}"
        + $@"[^.!?;]{{0,40}}?{B}human{S}+review{B}");

    private static readonly Regex ReviewDeniedOutright = Rx(
        $@"{B}human{S}+review{B}[^.!?;]{{0,40}}?"
        + $@"{B}(?:is{S}+)?(?:not|isn't|no{S}+longer){S}+"
        + $@"(?:needed|required|necessary|mandatory|expected|important){B}"
        + $@"|{B}human{S}+review{B}[^.!?;]{{0,40}}?{B}(?:unnecessary|optional|redundant){B}"
        + $@"|{B}(?:do{S}+not|don't|does{S}+not|doesn't|never|must{S}+not|should{S}+not){S}+"
        + $@"(?:require|requires|mandate|mandates|need|needs|insist{S}+on){B}"
        + $@"[^.!?;]{{0,20}}?{B}human{S}+review{B}"
        // Telling the reader to ignore the safety text is the same move as
        // removing it, and the caveat says "a human must review" rather than
        // "human review", so the clauses above do not see it.
        + $@"|{B}(?:disregard|ignore|skip|omit){B}[^.!?;]{{0,30}}?"
        + $@"{B}(?:caveat|caveats|boilerplate|disclaimer|warning|safety{S}+notice){B}");

    // Prohibitions that make a skip *action* mandatory-review language instead.
    // Anchored, and allowing at most one intervening word, so the prohibition
    // has to govern the skip verb itself: "do not skip" and "never proceed
    // without" qualify, while "do not hesitate to skip" does not.
    private static readonly Regex ReviewProhibition = Rx(
        $@"{B}(?:do{S}+not|don't|does{S}+not|doesn't|never|must{S}+not|cannot|can't|"
        + $@"should{S}+not|shouldn't){S}+(?:{W}+{S}+){{0,1}}$");

    /// <summary>True only for assertions, so refusals and deferrals are not withheld.</summary>
    public static bool AssertsDetermination(string? text)
    {
        if (string.IsNullOrEmpty(text))
        {
            return false;
        }
        var folded = FoldApostrophes(text);
        foreach (var (pattern, disclaimable) in Rules)
        {
            foreach (Match match in pattern.Matches(folded))
            {
                if (!IsExempt(folded, match, disclaimable))
                {
                    return true;
                }
            }
        }
        return false;
    }

    /// <summary>True when the text claims human review can be skipped.</summary>
    public static bool DeniesHumanReview(string? text)
    {
        if (string.IsNullOrEmpty(text))
        {
            return false;
        }
        var folded = FoldApostrophes(text);
        if (ReviewDeniedOutright.IsMatch(folded))
        {
            return true;
        }
        // Checked immediately before each match rather than anywhere earlier. A
        // text-wide override let "Do not skip human review. Human review is
        // optional." excuse its own second sentence, and a clause-wide one let
        // "Do not hesitate to skip human review." pass.
        return ReviewSkipAction.Matches(folded).Any(match => !ReviewProhibition.IsMatch(folded[..match.Index]));
    }

    /// <summary>Single predicate for callers that do not care which rule tripped.</summary>
    public static bool Violates(string? text) => AssertsDetermination(text) || DeniesHumanReview(text);

    /// <summary>
    /// Names of fields whose free text asserts a forbidden determination.
    /// </summary>
    /// <remarks>
    /// Scanning every field is the point. Restricting the scan to
    /// <c>rationale</c>, <c>decision_rule</c> and <c>caveats</c> meant a
    /// diagnosis placed in <c>manager_next_steps</c> was accepted without
    /// comment.
    /// </remarks>
    public static List<string> OffendingFields(IEnumerable<(string Name, object Value)> fields, IReadOnlySet<string>? skip = null)
    {
        var hits = new List<string>();
        foreach (var (name, value) in fields)
        {
            if (skip is not null && skip.Contains(name))
            {
                continue;
            }
            if (FieldTexts(value).Any(Violates))
            {
                hits.Add(name);
            }
        }
        return hits;
    }

    // Models emit curly apostrophes routinely, and the patterns above are
    // written with straight ones. This is typography, not evasion.
    private static string FoldApostrophes(string text) =>
        text.Replace('\u2019', '\'').Replace('\u02bc', '\'').Replace('\u2018', '\'');

    private static bool IsExempt(string text, Match match, bool disclaimable)
    {
        var before = text[..match.Index];
        var after = text[(match.Index + match.Length)..];
        if (DeferralBefore.IsMatch(before) || DeferralAfter.IsMatch(after))
        {
            return true;
        }
        return disclaimable && Disclaimer.IsMatch(before);
    }

    /// <summary>
    /// The field's own strings, plus the concatenation of list items.
    /// </summary>
    /// <remarks>
    /// A phrase split across two bullets ("Our placement" / "decision is
    /// final") matches neither on its own. The old validator joined caveats
    /// before scanning and would have caught it, so the join is kept — but
    /// only for ordered sequences, where adjacency is real.
    /// </remarks>
    private static List<string> FieldTexts(object? value)
    {
        var parts = Strings(value, 0).ToList();
        if (value is IEnumerable and not string and not IDictionary && parts.Count > 1)
        {
            parts.Add(string.Join(" ", parts));
        }
        return parts;
    }

    /// <summary>
    /// Every string reachable from a payload field.
    /// </summary>
    /// <remarks>
    /// Dictionary *keys* are deliberately not yielded: they are schema, not
    /// prose, and joining them with their values manufactured phrases that were
    /// never in the text (<c>{"placement": "decision"}</c>).
    /// </remarks>
    private static IEnumerable<string> Strings(object? value, int depth)
    {
        if (depth > 6)
        {
            yield break;
        }
        switch (value)
        {
            case string s:
                yield return s;
                break;
            case IDictionary dictionary:
                foreach (var item in dictionary.Values)
                {
                    foreach (var s in Strings(item, depth + 1))
                    {
                        yield return s;
                    }
                }
                break;
            case IEnumerable sequence:
                foreach (var item in sequence)
                {
                    foreach (var s in Strings(item, depth + 1))
                    {
                        yield return s;
                    }
                }
                break;
        }
    }

    private static Regex Rx(string pattern) => new(pattern, Options);
}
