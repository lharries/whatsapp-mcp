import { expect, test } from "bun:test"
import { INSTRUCTIONS } from "./instructions"

// Claude Code truncates MCP server instructions past 2048 characters.
test("instructions fit Claude Code's 2048-char limit", () => {
  expect(INSTRUCTIONS.length).toBeLessThanOrEqual(2048)
})

test("asking the operator comes before the event list", () => {
  expect(INSTRUCTIONS.indexOf("ask_poll")).toBeLessThan(INSTRUCTIONS.indexOf("EVENTS"))
})
