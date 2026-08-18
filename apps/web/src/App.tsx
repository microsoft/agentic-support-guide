import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { DashboardPage } from "./pages/DashboardPage";
import { AssessmentsPage } from "./pages/AssessmentsPage";
import { SupportsPage } from "./pages/SupportsPage";
import { AuditPage } from "./pages/AuditPage";
import { DemoGuidePage } from "./pages/DemoGuidePage";
import { PlaceholderPage } from "./pages/PlaceholderPage";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/assessments" element={<AssessmentsPage />} />
        <Route path="/supports" element={<SupportsPage />} />
        <Route path="/ai-audit" element={<AuditPage />} />
        <Route path="/demo-guide" element={<DemoGuidePage />} />
        <Route path="/learners" element={<PlaceholderPage />} />
        <Route path="/behavior" element={<PlaceholderPage />} />
        <Route path="/workforce" element={<PlaceholderPage />} />
        <Route path="/activities" element={<PlaceholderPage />} />
        <Route path="/readiness" element={<PlaceholderPage />} />
        <Route path="/correlations" element={<PlaceholderPage />} />
        <Route path="/alerts" element={<PlaceholderPage />} />
        <Route path="/access" element={<PlaceholderPage />} />
        <Route path="/settings" element={<PlaceholderPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
