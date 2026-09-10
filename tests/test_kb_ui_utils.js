const test = require("node:test");
const assert = require("node:assert/strict");
const {
  localDateKey, isStale, daysSince, filterItems, catalogParams, catalogState, sourceLabel,
} = require("../frontend/kb-ui-utils.js");

test("uses local calendar date instead of UTC date", () => {
  const beijingEarlyMorning = new Date("2026-09-08T23:30:00.000Z");
  assert.equal(localDateKey(beijingEarlyMorning), "2026-09-09");
  assert.equal(isStale("2026-09-09 · 每日更新", beijingEarlyMorning), false);
  assert.equal(isStale("2026-09-08 · 每日更新", beijingEarlyMorning), true);
});

test("extracts age from a section title", () => {
  const now = new Date("2026-09-09T04:00:00+08:00");
  assert.equal(daysSince("2026-09-02 · 每日更新", now), 7);
  assert.equal(daysSince("not-a-date", now), null);
});

test("filters the catalog by text, kind and freshness", () => {
  const items = [
    { line: "Redis cluster", kind: "questions", layer: "1", company: "ByteDance", day: "2026-09-09" },
    { line: "Agent platform", kind: "events", layer: "", company: "Tencent", day: "2026-09-02" },
    { line: "Redis basics", kind: "questions", layer: "1", company: "ByteDance", day: "" },
  ];
  const now = new Date("2026-09-09T04:00:00+08:00");
  assert.equal(filterItems(items, { query: "redis", kind: "questions", days: 7 }, now).length, 1);
  assert.equal(filterItems(items, { company: "tencent" }, now).length, 1);
});

test("builds server catalog parameters", () => {
  const params = new URLSearchParams(catalogParams({
    query: " redis ", kind: "questions", layer: "1", company: "ByteDance",
    space: "intel", days: 7,
  }, 3, 50));
  assert.deepEqual(Object.fromEntries(params), {
    q: "redis", kind: "questions", layer: "1", company: "ByteDance",
    space: "intel", days: "7", page: "3", page_size: "50",
  });
});

test("distinguishes loading, error, empty and ready catalog states", () => {
  assert.equal(catalogState(true, "", 2), "loading");
  assert.equal(catalogState(false, "network down", 0), "error");
  assert.equal(catalogState(false, "", 0), "empty");
  assert.equal(catalogState(false, "", 1), "ready");
});

test("uses source title or hostname as accessible link text", () => {
  assert.equal(sourceLabel({ title: "Original post", url: "https://example.com/a" }), "Original post");
  assert.equal(sourceLabel({ url: "https://docs.example.com/a" }), "docs.example.com");
  assert.equal(sourceLabel({ url: "javascript:alert(1)" }), "查看来源");
});
