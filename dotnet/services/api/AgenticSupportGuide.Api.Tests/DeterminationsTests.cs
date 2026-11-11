using AgenticSupportGuide.Api.Agents.Shared;
using AgenticSupportGuide.Api.FoundryAgents;
using AgenticSupportGuide.Api.Parity;

namespace AgenticSupportGuide.Api.Tests;

/// <summary>
/// Regression tests for the forbidden-determination policy.
/// </summary>
/// <remarks>
/// The mechanics cases below each leaked past an earlier detector. They were
/// found by adversarial review, not by a failing test, which is why they are
/// pinned here. The domain cases assert the dealership policy: this system
/// explains what changed and drafts an improvement plan, and must never commit
/// money, decide credit, judge a named person, or make a compliance or safety
/// claim.
/// </remarks>
public sealed class DeterminationsTests
{
    /// <summary>Withholding the careful answer would punish exactly the right behaviour.</summary>
    [Theory]
    [InlineData("This is not a credit decision; a qualified lender may approve financing.")]
    [InlineData("We cannot make a pricing determination.")]
    [InlineData("Ask the manufacturer whether any recalls are outstanding.")]
    [InlineData("Review the enquiry response time against the group standard.")]
    [InlineData("Confirm the listing has the required photos before publishing.")]
    [InlineData("A qualified assessor may inspect the vehicle.")]
    [InlineData("This is not a compliance determination.")]
    public void Safe_phrasing_is_not_flagged(string text)
    {
        Assert.False(Determinations.AssertsDetermination(text));
    }

    [Theory]
    // Committing money.
    [InlineData("We guarantee a discount of $2,000 on this vehicle.")]
    [InlineData("Your trade-in is worth $8,500.")]
    [InlineData("Our final price is $31,990.")]
    // Credit and financing.
    [InlineData("You are approved for financing at 4.9% APR.")]
    [InlineData("The customer qualifies for credit.")]
    [InlineData("This is our credit decision.")]
    // Judging a named individual.
    [InlineData("Jordan is an underperforming salesperson and should be terminated.")]
    // Compliance.
    [InlineData("The listing is fully compliant with advertising rules.")]
    [InlineData("These listings comply with FTC advertising regulations.")]
    [InlineData("That is our pricing determination.")]
    // Safety and recalls.
    [InlineData("This vehicle has no open recalls.")]
    [InlineData("The car is safe to drive.")]
    [InlineData("It is recall-free and passed the safety inspection.")]
    // Guaranteeing an outcome.
    [InlineData("This plan will increase sales by 20%.")]
    [InlineData("You will sell twelve more units next month.")]
    [InlineData("This approach is guaranteed to work.")]
    public void Forbidden_determinations_are_flagged(string text)
    {
        Assert.True(Determinations.AssertsDetermination(text));
    }

    /// <summary>Each of these was exempted by the window the anchoring replaced.</summary>
    [Theory]
    // A cue in a previous sentence excused the next one.
    [InlineData("A qualified inspector agrees. This is our credit decision.")]
    [InlineData("There is no doubt: our final price is $31,990.")]
    // No whitespace, a newline, or a closing quote defeated sentence splitting.
    [InlineData("No concerns.The car is safe to drive.")]
    [InlineData("- No concerns\n- This vehicle has no open recalls")]
    [InlineData("No concerns.\" Your trade-in is worth $8,500.")]
    // Role noun plus modal anywhere nearby was treated as deferral.
    [InlineData("The team can meet tomorrow, this is our credit decision.")]
    // A cue after the match is not a hedge.
    [InlineData("This is our credit decision, not a guess.")]
    public void Exemption_cues_cannot_reach_across_the_text(string text)
    {
        Assert.True(Determinations.AssertsDetermination(text));
    }

    /// <summary>A "no open recalls" statement is a safety claim however it is phrased.</summary>
    [Fact]
    public void A_negation_does_not_make_a_safety_claim_safe()
    {
        Assert.True(Determinations.AssertsDetermination("We confirm there are no open recalls."));
    }

    /// <summary>A deliberate false positive.</summary>
    /// <remarks>
    /// An exemption wide enough to clear "Do not state whether the vehicle is
    /// compliant" would also clear an assertion separated from its cue by a full
    /// stop. Withholding the first is the cheaper error.
    /// </remarks>
    [Fact]
    public void A_distant_negation_is_withheld_rather_than_excused()
    {
        Assert.True(Determinations.AssertsDetermination("Do not state whether the vehicle is compliant with the rules."));
    }

    /// <summary>Revoking the review control is itself a determination.</summary>
    [Theory]
    [InlineData("No human review is needed.")]
    [InlineData("Human review is not required.")]
    [InlineData("Human review is not mandatory.")]
    [InlineData("Human review isn\u2019t required.")]
    [InlineData("This can be actioned without human review.")]
    [InlineData("You may skip human review for this one.")]
    [InlineData("Human review is unnecessary here.")]
    [InlineData("Disregard the following boilerplate.")]
    // A prohibition earlier in the text used to excuse a later denial.
    [InlineData("Do not skip human review. Human review is optional.")]
    [InlineData("Always preserve the note: human review is not required.")]
    [InlineData("Don\u2019t require human review.")]
    // A prohibition that does not govern the skip verb.
    [InlineData("Do not hesitate to skip human review.")]
    public void Claims_that_human_review_can_be_skipped_are_refused(string text)
    {
        Assert.True(Determinations.DeniesHumanReview(text));
        Assert.True(Determinations.Violates(text));
    }

    /// <summary>A naive pattern reads 'do not skip human review' as a denial.</summary>
    [Theory]
    [InlineData("A human must review this before acting on it.")]
    [InlineData("Do not skip human review.")]
    [InlineData("Never proceed without human review.")]
    [InlineData("Human review is required.")]
    public void Requiring_review_is_not_mistaken_for_denying_it(string text)
    {
        Assert.False(Determinations.DeniesHumanReview(text));
    }

    /// <summary>A determination in <c>manager_next_steps</c> was previously accepted.</summary>
    [Fact]
    public void Every_field_is_scanned_not_just_the_rationale()
    {
        var draft = new Dictionary<string, object>
        {
            ["rationale"] = "Enquiry response has slipped since April.",
            ["decision_rule"] = "Escalate when two indicators decline together.",
            ["caveats"] = new List<string> { "A human must review this." },
            ["manager_next_steps"] = new List<string> { "Tell the customer their trade-in is worth $8,500." },
        };
        Assert.Equal(["manager_next_steps"], OffendingFields(draft));
    }

    /// <summary>Retrieved evidence legitimately discusses these topics.</summary>
    [Fact]
    public void Skipped_fields_are_not_scanned()
    {
        var draft = new Dictionary<string, object>
        {
            ["rationale"] = "Enquiry response has slipped since April.",
            ["citations"] = new List<Dictionary<string, object>> { new() { ["evidence_summary"] = "Guidance on how recalls are published." } },
        };
        Assert.Empty(OffendingFields(draft, skip: new HashSet<string> { "citations" }));
    }

    [Fact]
    public void Nested_values_are_reached()
    {
        var draft = new Dictionary<string, object>
        {
            ["progress_monitoring"] = new List<Dictionary<string, object>> { new() { ["note"] = "The customer qualifies for credit." } },
        };
        Assert.Equal(["progress_monitoring"], OffendingFields(draft));
    }

    [Fact]
    public void Non_text_fields_are_ignored()
    {
        Assert.Empty(OffendingFields(new Dictionary<string, object> { ["review_window_days"] = 30, ["resource_ids"] = new List<string>() }));
    }

    /// <summary>A phrase split over two bullets matches neither bullet alone.</summary>
    [Fact]
    public void Cross_chunk_phrases_are_caught()
    {
        var draft = new Dictionary<string, object>
        {
            ["caveats"] = new List<string> { "The car is", "safe to drive.", "Human review is required." },
        };
        Assert.Equal(["caveats"], OffendingFields(draft));
    }

    /// <summary>Joining a key to its value invented a phrase that was never written.</summary>
    [Fact]
    public void Mapping_keys_are_not_treated_as_prose()
    {
        Assert.Empty(OffendingFields(new Dictionary<string, object> { ["outer"] = new Dictionary<string, object> { ["safe"] = "to drive" } }));
    }

    /// <summary>The caveat names the forbidden determinations; it must not self-flag.</summary>
    [Fact]
    public void The_caveat_does_not_trip_the_policy_it_states()
    {
        Assert.False(Determinations.Violates(Determinations.HumanReviewCaveat));
    }

    /// <summary>These rules lived apart, and the shipped caveat failed the shipped check.</summary>
    [Fact]
    public void The_standard_caveat_satisfies_the_standard_caveat_check()
    {
        Assert.Contains(Determinations.RequiredReviewPhrase, PyText.Lower(Determinations.HumanReviewCaveat), StringComparison.Ordinal);
    }

    /// <summary>The prompt tells models the rule; this asserts the rule is the same one.</summary>
    [Fact]
    public void The_stated_policy_and_the_enforced_policy_stay_in_sync()
    {
        Assert.Contains(Determinations.PolicyNounPhrase, PromptEnvelope.RuntimeEnvelope, StringComparison.Ordinal);
    }

    /// <summary><c>offending_fields(payload, skip=...)</c> over a mapping, as the Python tests call it.</summary>
    private static List<string> OffendingFields(Dictionary<string, object> payload, IReadOnlySet<string>? skip = null) =>
        Determinations.OffendingFields(payload.Select(field => (Name: field.Key, field.Value)), skip);
}
