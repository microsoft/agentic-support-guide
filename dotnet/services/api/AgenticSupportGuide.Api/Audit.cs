using System.Globalization;

namespace AgenticSupportGuide.Api;

/// <summary>Audit event view over the seeded synthetic rows.</summary>
public static class Audit
{
    public static List<AuditEvent> ListEvents(IReadOnlyList<AuditRow> rows) =>
        rows.Select(r => new AuditEvent
        {
            EventId = r.EventId,
            Timestamp = r.Timestamp,
            Endpoint = r.Endpoint,
            Context = r.Context,
            User = r.User,
            ProviderModel = r.ProviderModel,
            DurationMs = r.DurationMs,
            TokenEstimate = r.TokenEstimate,
            Status = r.Status,
        }).ToList();

    /// <summary>Wall-clock UTC time in the API's timestamp format.</summary>
    public static string UtcNowIso() => DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture);
}

/// <summary>
/// Runtime audit metadata store.
/// </summary>
/// <remarks>
/// Runtime rows are metadata only: agent name, endpoint, provider/model,
/// duration, token estimate, status, correlation_id, dealer_group_id, evidence
/// counts, validator status. Never prompts, completions, secrets, or raw
/// concern text.
/// </remarks>
public sealed class RuntimeAuditLog(int maxRows = 500)
{
    private readonly Lock _lock = new();
    private List<AuditEvent> _rows = [];
    private int _counter;

    public void Append(
        string endpoint,
        string context,
        string providerModel,
        int durationMs,
        int tokenEstimate,
        string status,
        string user = "S-01",
        string correlationId = "",
        string dealerGroupId = "",
        int evidenceCount = 0,
        int citationCount = 0,
        string validatorStatus = "")
    {
        lock (_lock)
        {
            _counter++;
            _rows.Add(new AuditEvent
            {
                EventId = $"AUD-R{_counter:00000}",
                Timestamp = Audit.UtcNowIso(),
                Endpoint = endpoint,
                Context = context,
                User = user,
                ProviderModel = providerModel,
                DurationMs = durationMs,
                TokenEstimate = tokenEstimate,
                Status = status,
                CorrelationId = correlationId,
                DealerGroupId = dealerGroupId,
                EvidenceCount = evidenceCount,
                CitationCount = citationCount,
                ValidatorStatus = validatorStatus,
            });
            Trim();
        }
    }

    /// <summary>Record a human-review state transition as a safe audit row.</summary>
    public void AppendReviewTransition(ReviewTransitionAuditEntry entry)
    {
        lock (_lock)
        {
            _counter++;
            _rows.Add(new AuditEvent
            {
                EventId = $"AUD-R{_counter:00000}",
                Timestamp = entry.Timestamp,
                Endpoint = "/api/supports/plans/{plan_id}/review",
                Context = $"review:{entry.PreviousState}->{entry.NewState}",
                User = entry.UserLabel,
                ProviderModel = "human-review",
                DurationMs = 0,
                TokenEstimate = 0,
                Status = entry.NewState,
                CorrelationId = entry.CorrelationId,
                DealerGroupId = entry.DealerGroupId,
                EvidenceCount = entry.EvidenceCount,
                CitationCount = 0,
                ValidatorStatus = entry.ValidatorVerdict,
            });
            Trim();
        }
    }

    public List<AuditEvent> Snapshot()
    {
        lock (_lock)
        {
            return [.. _rows];
        }
    }

    public int Clear()
    {
        lock (_lock)
        {
            var removed = _rows.Count;
            _rows = [];
            _counter = 0;
            return removed;
        }
    }

    private void Trim()
    {
        if (_rows.Count > maxRows)
        {
            _rows = _rows[^maxRows..];
        }
    }
}
