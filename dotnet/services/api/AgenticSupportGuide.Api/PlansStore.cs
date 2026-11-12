namespace AgenticSupportGuide.Api;

/// <summary>
/// In-memory saved support plans, initialized from seeded specs.
/// </summary>
/// <remarks>
/// Seeded plans use deterministic stub <see cref="Recommendation"/> objects so
/// startup never requires Azure connectivity. Real recommendations come from
/// the agent workflow when the user runs the plan builder.
///
/// Process-local; resets on server restart. Requests are served concurrently,
/// so every mutation is guarded. Retention is capped so a long-lived process
/// cannot grow without bound from repeated saves.
/// </remarks>
public sealed class SavedPlansStore(int maxPlans = 500)
{
    private const string StubDealerGroup = "GROUP-DEMO";

    private static readonly string[] StubCaveats =
    [
        "Illustrative synthetic output only; not a real benchmark.",
        "Human review is required before any decision or communication.",
    ];

    private readonly Lock _lock = new();
    private List<SavedPlan> _plans = [];
    private int _counter;

    public void Seed(IReadOnlyList<SeededPlanSpec> specs, IReadOnlyList<Dealership> dealerships)
    {
        var known = dealerships.Select(d => d.DealershipId).ToHashSet();
        // Every other mutator takes the lock. `demo/reset` calls this while
        // other requests are reading and appending, so without it the list and
        // the id counter can diverge.
        lock (_lock)
        {
            foreach (var spec in specs)
            {
                if (!known.Contains(spec.DealershipId))
                {
                    continue;
                }
                _plans.Add(new SavedPlan(
                    PlanId: spec.PlanId,
                    DealershipId: spec.DealershipId,
                    DealerGroupId: StubDealerGroup,
                    Category: spec.Category,
                    ConcernText: spec.ConcernText,
                    SelectedGoal: spec.SelectedGoalId,
                    SelectedStrategies: [.. spec.SelectedStrategyIds],
                    CreatedAt: spec.CreatedAt,
                    Recommendation: StubRecommendation(spec.Category),
                    HumanReviewState: HumanReview.PendingReview));
                _counter++;
            }
        }
    }

    public List<SavedPlan> List()
    {
        lock (_lock)
        {
            return [.. _plans];
        }
    }

    public SavedPlan? Get(string planId)
    {
        lock (_lock)
        {
            return _plans.FirstOrDefault(p => p.PlanId == planId);
        }
    }

    public SavedPlan Add(SavedPlan plan)
    {
        lock (_lock)
        {
            _plans.Add(plan);
            if (_plans.Count > maxPlans)
            {
                _plans = _plans[^maxPlans..];
            }
            return plan;
        }
    }

    public SavedPlan Replace(SavedPlan plan)
    {
        lock (_lock)
        {
            var index = _plans.FindIndex(p => p.PlanId == plan.PlanId);
            if (index < 0)
            {
                throw new KeyNotFoundException(plan.PlanId);
            }
            _plans[index] = plan;
            return plan;
        }
    }

    public string NextPlanId()
    {
        lock (_lock)
        {
            _counter++;
            return $"PLN-U{_counter:0000}";
        }
    }

    public int Clear()
    {
        lock (_lock)
        {
            var removed = _plans.Count;
            _plans = [];
            _counter = 0;
            return removed;
        }
    }

    private static Recommendation StubRecommendation(string category) =>
        new(
            DealerGroupId: StubDealerGroup,
            DetectedNeed: $"Seeded example for category '{category}'.",
            EvidenceSummary: ["Synthetic seeded evidence line 1.", "Synthetic seeded evidence line 2."],
            Rationale: "Seeded example recommendation. Regenerate via the plan builder for a live agent-produced version.",
            SupportTier: "Focused",
            RecommendedFrequency: "weekly review, 20-25 min",
            GroupingGuidance: "single dealership with group oversight",
            ResourceMatches: [new RecommendationResource("RES-001", "Seeded Kit 001", "playbook")],
            ManagerNextSteps: ["Confirm the review slot.", "Brief the sales manager."],
            ProgressMonitoring: ["Weekly check on the agreed measure."],
            ReviewWindowDays: 28,
            DecisionRule: "Seeded stub - see the coordinator for live decision rules.",
            Caveats: [.. StubCaveats],
            GoalSuggestions: [$"GOAL-{category}-1"],
            StrategySuggestions: [$"ST-{category}-1"],
            Citations:
            [
                new RecommendationCitation(
                    CitationId: $"{StubDealerGroup}-seed-{category}",
                    DealerGroupId: StubDealerGroup,
                    SourceType: "synthetic_fixture",
                    SourceTitle: "Seeded synthetic fixture",
                    SectionOrPage: "",
                    EvidenceSummary: "Seeded synthetic citation attached to a stub plan.",
                    SourceRef: $"fixture://{StubDealerGroup.ToLowerInvariant()}/{category}/seed",
                    RetrievedAt: "2026-01-05T09:00:00Z",
                    Confidence: 0.7),
            ],
            Completeness: new Dictionary<string, object> { ["ok"] = true, ["missing"] = new List<string>() },
            HumanReviewState: HumanReview.PendingReview,
            GeneratedBy: "Seeded synthetic stub. Not a real agent output.");
}
