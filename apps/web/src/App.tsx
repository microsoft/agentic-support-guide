import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { DashboardPage } from "./pages/DashboardPage";
import { AssessmentsPage } from "./pages/AssessmentsPage";
import { SupportsPage } from "./pages/SupportsPage";
import { AuditPage } from "./pages/AuditPage";
import { DemoGuidePage } from "./pages/DemoGuidePage";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/assessments" element={<AssessmentsPage />} />
        <Route path="/supports" element={<SupportsPage />} />
        <Route path="/ai-audit" element={<AuditPage />} />
        <Route path="/demo-guide" element={<DemoGuidePage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
