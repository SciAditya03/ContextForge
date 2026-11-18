import { fireEvent, render, screen } from "@testing-library/react";
import { CoverageMeter, LanguageBar, SeverityBars } from "./charts";

describe("charts", () => {
  it("language bar folds languages beyond the 7th into Other and shows a legend with values", () => {
    const langs = Object.fromEntries(["A", "B", "C", "D", "E", "F", "G", "H", "I"].map((n, i) => [n, { files: 1, code_lines: 100 - i * 5 }]));
    render(<LanguageBar languages={langs} />);
    expect(screen.getByText("Other (2)")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Lines of code by language" })).toBeInTheDocument();
  });

  it("coverage meter lists every non-empty status", () => {
    render(<CoverageMeter summary={{ analysed: 3, deterministic_only: 5, excluded: 2 }} />);
    expect(screen.getByText("AI + deterministic")).toBeInTheDocument();
    expect(screen.getByText("Excluded")).toBeInTheDocument();
    expect(screen.queryByText("Failed")).not.toBeInTheDocument();
  });

  it("severity bars are filterable", () => {
    const onSelect = vi.fn();
    render(<SeverityBars counts={{ high: 2, low: 1 }} onSelect={onSelect} />);
    fireEvent.click(screen.getByTitle("High: 2 findings"));
    expect(onSelect).toHaveBeenCalledWith("high");
  });
});
