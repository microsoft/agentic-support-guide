import { useLocation } from "react-router-dom";
import { Card } from "../components/Card";

export function PlaceholderPage() {
  const { pathname } = useLocation();
  return (
    <Card title="Module preview">
      <p className="text-slate-300">Module not implemented in this prototype.</p>
      <p className="mt-2 text-xs text-slate-500">Route: {pathname}</p>
    </Card>
  );
}
