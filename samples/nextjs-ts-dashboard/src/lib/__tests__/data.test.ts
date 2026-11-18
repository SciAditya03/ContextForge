import { describe, expect, it } from "vitest";
import { findProject, listProjects } from "../data";

describe("data", () => {
  it("lists projects", () => {
    expect(listProjects().length).toBeGreaterThan(0);
    expect(findProject("p1")?.name).toBe("Website redesign");
  });
});
