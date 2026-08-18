export function LoadingState({ label = "Loading..." }: { label?: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="rounded-lg border border-slate-800 bg-slate-900/50 p-6 text-slate-300"
    >
      {label}
    </div>
  );
}

export function EmptyState({ label = "No data available." }: { label?: string }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-700 bg-slate-900/40 p-6 text-slate-400">
      {label}
    </div>
  );
}

export function ApiUnavailable({ onRetry }: { onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-6 text-rose-200"
    >
      <div className="font-semibold">API unavailable - start the local backend.</div>
      <p className="mt-1 text-sm text-rose-100/80">
        Confirm the FastAPI service is running at http://127.0.0.1:8000. See the
        troubleshooting section in the README for CORS and port guidance.
      </p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded bg-rose-500/20 border border-rose-400/50 px-3 py-1 text-sm text-rose-50 hover:bg-rose-500/30"
        >
          Retry
        </button>
      )}
    </div>
  );
}
