using AgenticSupportGuide.Api.Agents.Shared;

namespace AgenticSupportGuide.Api.Evidence;

/// <summary>
/// Synthetic per-dealer-group evidence fixtures.
/// </summary>
/// <remarks>
/// Every entry is deterministic and generic. Nothing here references real
/// customer, group, dealership, staff, or document names. Groups are named
/// <c>GROUP-A</c>, <c>GROUP-B</c>, and <c>GROUP-DEMO</c> to reinforce that
/// these are placeholders.
///
/// A dealer group is an ownership boundary, not a franchise brand, so two
/// groups selling the same brand must never see each other's evidence.
///
/// Production replacement: a Fabric-backed retriever that reads from the
/// per-group lakehouse and optionally the group's approved document library.
/// That retriever should keep the same interface.
/// </remarks>
public sealed class FixtureEvidenceRetriever(IReadOnlyDictionary<string, IReadOnlyDictionary<string, IReadOnlyList<Citation>>>? catalog = null) : IEvidenceRetriever
{
    private static readonly IReadOnlyDictionary<string, IReadOnlyDictionary<string, IReadOnlyList<Citation>>> DealerGroups = BuildCatalog();

    private readonly IReadOnlyDictionary<string, IReadOnlyDictionary<string, IReadOnlyList<Citation>>> _catalog = catalog ?? DealerGroups;

    public string ProviderName => "fixture";

    public string ProviderModel => "synthetic";

    public bool EvidenceVerifiable => true;

    public static IReadOnlyList<string> ListAvailableDealerGroups() => [.. DealerGroups.Keys.Order(StringComparer.Ordinal)];

    public bool HasDealerGroup(string dealerGroupId) => _catalog.ContainsKey(dealerGroupId);

    public Task<EvidenceBundle> RetrieveAsync(EvidenceRequest request, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrEmpty(request.DealerGroupId))
        {
            throw new EvidenceRetrievalException("MISSING_DEALER_GROUP_ID", "Evidence request is missing a dealer_group_id.");
        }
        if (!_catalog.TryGetValue(request.DealerGroupId, out var byCategory))
        {
            throw new EvidenceRetrievalException("UNKNOWN_DEALER_GROUP", $"No synthetic evidence configured for group '{request.DealerGroupId}'.");
        }
        var items = byCategory.TryGetValue(request.Category, out var found) ? found.ToList() : [];
        // Defensive: refuse to return any item whose group tag disagrees.
        if (items.Any(c => c.DealerGroupId != request.DealerGroupId))
        {
            throw new CrossDealerGroupEvidenceException("CROSS_DEALER_GROUP_CITATION", "Fixture returned a citation from a different dealer group.");
        }
        if (request.MaxItems > 0)
        {
            items = items.Take(request.MaxItems).ToList();
        }
        return Task.FromResult(new EvidenceBundle(request.DealerGroupId, items));
    }

    private static Citation Fixture(string group, string cid, string kind, string title, string summary) =>
        new(
            CitationId: $"{group}-{cid}",
            DealerGroupId: group,
            SourceType: kind,
            SourceTitle: title,
            SectionOrPage: "section 1",
            EvidenceSummary: summary,
            SourceRef: $"fixture://{group.ToLowerInvariant()}/{cid}",
            RetrievedAt: Audit.UtcNowIso(),
            Confidence: 0.8);

    private static Dictionary<string, IReadOnlyDictionary<string, IReadOnlyList<Citation>>> BuildCatalog() => new()
    {
        ["GROUP-A"] = new Dictionary<string, IReadOnlyList<Citation>>
        {
            ["lead-response"] =
            [
                Fixture("GROUP-A", "lead-01", CitationSourceType.StructuredData, "Group A - Enquiry Response Benchmarks",
                    "Synthetic benchmark describing the expected first-response window for the current review period."),
                Fixture("GROUP-A", "lead-02", CitationSourceType.Resource, "Group A - Approved Enquiry Handling Routines",
                    "Synthetic resource catalog entry describing an allowed daily enquiry triage routine."),
            ],
            ["test-drive-conversion"] =
            [
                Fixture("GROUP-A", "drive-01", CitationSourceType.Policy, "Group A - Test Drive Booking Standard",
                    "Synthetic policy summary describing confirmation and preparation steps."),
            ],
            ["listing-completeness"] =
            [
                Fixture("GROUP-A", "listing-01", CitationSourceType.Policy, "Group A - Listing Publication Checklist",
                    "Synthetic checklist describing the photo and specification fields required before a listing publishes."),
            ],
            ["inventory-ageing"] =
            [
                Fixture("GROUP-A", "ageing-01", CitationSourceType.StructuredData, "Group A - Inventory Review Cadence",
                    "Synthetic reference describing how often each vehicle is reviewed and who signs the review off."),
            ],
            ["price-data-freshness"] =
            [
                Fixture("GROUP-A", "price-01", CitationSourceType.Policy, "Group A - Advertised Price Refresh Standard",
                    "Synthetic policy summary describing the price refresh cadence and owner."),
            ],
            ["multi-area"] =
            [
                Fixture("GROUP-A", "multi-01", CitationSourceType.Policy, "Group A - Coordinated Process Review Policy",
                    "Synthetic policy summary describing how enquiry handling, test drives, and listing quality are reviewed in one plan."),
            ],
        },
        ["GROUP-B"] = new Dictionary<string, IReadOnlyList<Citation>>
        {
            ["lead-response"] =
            [
                Fixture("GROUP-B", "lead-01", CitationSourceType.Document, "Group B - Enquiry Handling Handbook",
                    "Synthetic handbook excerpt describing response-time expectations by enquiry channel."),
            ],
            ["test-drive-conversion"] =
            [
                Fixture("GROUP-B", "drive-01", CitationSourceType.Document, "Group B - Test Drive Handbook",
                    "Synthetic handbook excerpt describing rebooking after a no-show."),
            ],
            ["listing-completeness"] =
            [
                Fixture("GROUP-B", "listing-01", CitationSourceType.Document, "Group B - Listing Standards Handbook",
                    "Synthetic handbook excerpt describing the required listing field set."),
            ],
            ["inventory-ageing"] =
            [
                Fixture("GROUP-B", "ageing-01", CitationSourceType.Resource, "Group B - Approved Review Cadence Catalog",
                    "Synthetic resource catalog entry describing allowed review routines."),
            ],
            ["price-data-freshness"] =
            [
                Fixture("GROUP-B", "price-01", CitationSourceType.Document, "Group B - Price Data Handbook",
                    "Synthetic handbook excerpt describing the price refresh exception report."),
            ],
            ["multi-area"] =
            [
                Fixture("GROUP-B", "multi-01", CitationSourceType.Document, "Group B - Coordinated Improvement Handbook",
                    "Synthetic handbook excerpt describing coordinated multi-area planning."),
            ],
        },
        ["GROUP-DEMO"] = new Dictionary<string, IReadOnlyList<Citation>>
        {
            ["lead-response"] =
            [
                Fixture("GROUP-DEMO", "lead-01", CitationSourceType.SyntheticFixture, "Demo group - Enquiry Response Benchmarks",
                    "Synthetic benchmark describing the expected first-response window for online enquiries and the median response time recorded this review period."),
                Fixture("GROUP-DEMO", "lead-02", CitationSourceType.SyntheticFixture, "Demo group - Follow-up Monitoring Guide",
                    "Synthetic guide describing a weekly follow-up cadence for unanswered enquiries and how leads awaiting a reply are escalated."),
            ],
            ["test-drive-conversion"] =
            [
                Fixture("GROUP-DEMO", "drive-01", CitationSourceType.SyntheticFixture, "Demo group - Test Drive Conversion Notes",
                    "Synthetic notes describing how booked test drive appointments are confirmed and how attendance converts to completed sales conversations."),
            ],
            ["listing-completeness"] =
            [
                Fixture("GROUP-DEMO", "listing-01", CitationSourceType.SyntheticFixture, "Demo group - Listing Completeness Standard",
                    "Synthetic standard describing the photographs, specification fields, and pricing detail a vehicle listing must carry before publication."),
            ],
            ["inventory-ageing"] =
            [
                Fixture("GROUP-DEMO", "ageing-01", CitationSourceType.SyntheticFixture, "Demo group - Inventory Ageing Review",
                    "Synthetic review describing how ageing stock is identified by days in inventory and how on-time review cadence is tracked."),
            ],
            ["price-data-freshness"] =
            [
                Fixture("GROUP-DEMO", "price-01", CitationSourceType.SyntheticFixture, "Demo group - Price Data Freshness Policy",
                    "Synthetic policy describing how often advertised price data is refreshed against market guidance and what counts as stale pricing."),
            ],
            ["multi-area"] =
            [
                Fixture("GROUP-DEMO", "multi-01", CitationSourceType.SyntheticFixture, "Demo group - Coordinated Review Policy",
                    "Synthetic policy summary describing how enquiry handling, test drives, and listing quality are reviewed together rather than area by area."),
            ],
        },
    };
}
