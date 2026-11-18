import { render, screen } from "@testing-library/react";
import { EvidenceBadge, SeverityBadge, SourceChip } from "./badges";

describe("domain badges", () => {
  it("renders evidence classes with explanatory titles", () => {
    render(<EvidenceBadge value="AI_INTERPRETED" />);
    expect(screen.getByText("AI")).toHaveAttribute("title", expect.stringContaining("validated source references"));
  });

  it("pairs severity colour with a text label", () => {
    render(<SeverityBadge value="critical" />);
    expect(screen.getByText("Critical")).toBeInTheDocument();
  });

  it("formats source references", () => {
    render(<SourceChip file="app/main.py" start={4} end={9} />);
    expect(screen.getByText("app/main.py:4-9")).toBeInTheDocument();
  });
});
