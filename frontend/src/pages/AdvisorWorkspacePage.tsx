import { useSearchParams } from "react-router-dom";
import { PageHeader } from "../components/PageHeader";
import { AdvisorPage } from "./AdvisorPage";
import { ReportsPage } from "./ReportsPage";

type AdvisorTab = "advisor" | "reports";

function advisorTab(value: string | null): AdvisorTab {
  return value === "reports" ? "reports" : "advisor";
}

export function AdvisorWorkspacePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = advisorTab(searchParams.get("tab"));
  const selectTab = (next: AdvisorTab) => {
    const params = new URLSearchParams(searchParams);
    params.set("tab", next);
    setSearchParams(params, { replace: true });
  };

  const actions = (
    <div className="segmented-control workspace-tabs" aria-label="Advisor view">
      <button type="button" className={tab === "advisor" ? "active" : ""} onClick={() => selectTab("advisor")}>Advisor</button>
      <button type="button" className={tab === "reports" ? "active" : ""} onClick={() => selectTab("reports")}>Reports</button>
    </div>
  );

  return (
    <div className="page-container consolidated-page advisor-workspace">
      <PageHeader title="Advisor" description="Ask Budget for guidance or open deterministic reports without leaving the workspace." actions={actions} />
      <div className="embedded-workspace">
        {tab === "reports" ? <ReportsPage embedded /> : <AdvisorPage embedded />}
      </div>
    </div>
  );
}
