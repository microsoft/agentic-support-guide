export function PrototypeBanner() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="w-full bg-amber-500/15 border-b border-amber-400/40 text-amber-100 text-sm px-4 py-2 text-center"
    >
      Prototype - synthetic data, three agents backed by Azure AI Foundry, not a production system.
    </div>
  );
}
