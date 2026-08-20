import { useSearchParams } from "react-router-dom";
import { PageHeader } from "../components/PageHeader";
import { InsightsPage } from "./InsightsPage";
import { TrendsPage } from "./TrendsPage";

type AnalyticsTab = "insights" | "trends";

function analyticsTab(value: string | null): AnalyticsTab {
  return value === "trends" ? "trends" : "insights";
}

export function AnalyticsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = analyticsTab(searchParams.get("tab"));
  const selectTab = (next: AnalyticsTab) => {
    const params = new URLSearchParams(searchParams);
    params.set("tab", next);
    setSearchParams(params, { replace: true });
  };

  const actions = (
    <div className="segmented-control workspace-tabs" aria-label="Analytics view">
      <button type="button" className={tab === "insights" ? "active" : ""} onClick={() => selectTab("insights")}>Insights</button>
      <button type="button" className={tab === "trends" ? "active" : ""} onClick={() => selectTab("trends")}>Trends</button>
    </div>
  );

  return (
    <div className="page-container consolidated-page analytics-workspace">
      <PageHeader title="Analytics" description="Signals, trends, and the financial patterns behind your money." actions={actions} />
      <div className="embedded-workspace">
        {tab === "insights" ? <InsightsPage embedded /> : <TrendsPage embedded />}
      </div>
    </div>
  );
}
