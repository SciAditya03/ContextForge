import GithubSlugger from "github-slugger";
import { compactNumber, extractHeadings, formatBytes, sourceLabel } from "./utils";

describe("utils", () => {
  it("formats sizes and numbers", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(3 * 1024 * 1024)).toBe("3.0 MB");
    expect(compactNumber(15300)).toBe("15.3K");
  });

  it("builds source labels", () => {
    expect(sourceLabel("a.py")).toBe("a.py");
    expect(sourceLabel("a.py", 3)).toBe("a.py:3");
    expect(sourceLabel("a.py", 3, 9)).toBe("a.py:3-9");
  });

  it("extracts headings with ids matching rehype-slug, skipping code blocks", () => {
    const md = "# Title\n\n## 1. Project Overview\n```\n## not a heading\n```\n### `POST /api/x`\n## Dup\n## Dup\n#### Deep";
    const h = extractHeadings(md, new GithubSlugger(), 3);
    expect(h.map((x) => x.id)).toEqual(["title", "1-project-overview", "post-apix", "dup", "dup-1"]);
    expect(h[2].text).toBe("POST /api/x");
  });
});
