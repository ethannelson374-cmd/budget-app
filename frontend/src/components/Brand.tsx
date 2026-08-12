import { Link } from "react-router-dom";
import { Icon } from "./Icon";

export function Brand({ linked = true }: { linked?: boolean }) {
  const content = (
    <span className="brand-content">
      <span className="brand-mark" aria-hidden="true"><Icon name="wallet" /></span>
      <span>Budget</span>
    </span>
  );
  return linked ? <Link className="brand" to="/dashboard" aria-label="Budget home">{content}</Link> : <div className="brand">{content}</div>;
}
