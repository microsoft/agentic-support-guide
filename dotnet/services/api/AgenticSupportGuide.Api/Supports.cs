namespace AgenticSupportGuide.Api;

/// <summary>Support options catalog: the categories, goals and strategies a plan can use.</summary>
public static class Supports
{
    public static readonly IReadOnlyList<CategoryOption> Categories =
    [
        new("lead-response", "Enquiry Response", "Speed and completeness of the first reply to an online enquiry."),
        new("test-drive-conversion", "Test Drives", "Booking, confirming, and attending scheduled test drives."),
        new("listing-completeness", "Listing Completeness", "Required photos, specification, and label data present on a listing."),
        new("inventory-ageing", "Inventory Review Cadence", "Whether scheduled ageing reviews are completed on time."),
        new("price-data-freshness", "Price Data Freshness", "Keeping advertised price data refreshed on the agreed cadence."),
        new("multi-area", "Multi-Area Plan", "Coordinated plan across enquiry handling, test drives, and listings."),
    ];

    private static readonly (string Category, string[] Texts)[] GoalTemplates =
    [
        ("lead-response",
        [
            "Reduce median first response to online enquiries to under 30 minutes in 6 weeks.",
            "Reply to 90% of enquiries within the same business day for 8 consecutive weeks.",
        ]),
        ("test-drive-conversion",
        [
            "Raise attended-to-booked test drive ratio by 15 percentage points in 8 weeks.",
            "Confirm every booked test drive within 24 hours for 6 consecutive weeks.",
        ]),
        ("listing-completeness",
        [
            "Publish 95% of new listings with the full required photo set within 6 weeks.",
            "Carry complete specification and label data on every new listing for 8 weeks.",
        ]),
        ("inventory-ageing",
        [
            "Complete every scheduled ageing review on time for 8 consecutive weeks.",
            "Close the review backlog to zero outstanding items within 6 weeks.",
        ]),
        ("price-data-freshness",
        [
            "Refresh advertised price data on the agreed cadence for 8 consecutive weeks.",
            "Reduce the count of stale price records to under 5% within 6 weeks.",
        ]),
        ("multi-area",
        [
            "Lift enquiry response and test drive attendance by 10% each in 8 weeks.",
            "Complete a coordinated cross-area process review with the group team.",
        ]),
    ];

    private static readonly (string Category, string[] Texts)[] StrategyTemplates =
    [
        ("lead-response",
        [
            "Named owner for the enquiry inbox during every opening hour.",
            "Standard first-reply template covering availability and next step.",
            "Daily review of enquiries still unanswered after two hours.",
        ]),
        ("test-drive-conversion",
        [
            "Confirmation message the day before every booked test drive.",
            "Prepare and stage the vehicle the evening before the appointment.",
            "Same-day follow-up on every no-show to rebook.",
        ]),
        ("listing-completeness",
        [
            "Photo and data checklist signed off before a listing publishes.",
            "Weekly audit of live listings against the required field set.",
            "Single owner for label and specification data per listing.",
        ]),
        ("inventory-ageing",
        [
            "Calendar the ageing review and protect the slot.",
            "Escalate any review more than seven days overdue.",
            "Weekly report of outstanding reviews to the general manager.",
        ]),
        ("price-data-freshness",
        [
            "Scheduled refresh window for advertised price data.",
            "Exception report listing records not refreshed on cadence.",
            "Named owner for price data per vehicle line.",
        ]),
        ("multi-area",
        [
            "Coordinated process review meeting every two weeks.",
            "Shared improvement tracker across managers and the group team.",
            "Bi-weekly group update summarising movement across areas.",
        ]),
    ];

    public static SupportOptions BuildSupportOptions(IEnumerable<(string Id, string Label)> dealershipLabels, IReadOnlyList<string>? dealerGroups = null) =>
        new(
            Dealerships: dealershipLabels.Select(d => new Option(d.Id, d.Label)).ToList(),
            Categories: Categories,
            Goals: Goals(),
            Strategies: Strategies(),
            DealerGroups: dealerGroups ?? []);

    private static List<GoalOption> Goals() =>
        GoalTemplates
            .SelectMany(t => t.Texts.Select((text, i) => new GoalOption($"GOAL-{t.Category}-{i + 1}", $"Goal {i + 1}", t.Category, text)))
            .ToList();

    private static List<StrategyOption> Strategies() =>
        StrategyTemplates
            .SelectMany(t => t.Texts.Select((text, i) => new StrategyOption($"ST-{t.Category}-{i + 1}", $"Strategy {i + 1}", t.Category, text)))
            .ToList();
}
