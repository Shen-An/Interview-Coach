(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.KbUi = factory();
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function localDateKey(value) {
    const date = value instanceof Date ? value : new Date(value == null ? Date.now() : value);
    if (Number.isNaN(date.getTime())) return "";
    return [
      date.getFullYear(),
      String(date.getMonth() + 1).padStart(2, "0"),
      String(date.getDate()).padStart(2, "0"),
    ].join("-");
  }

  function extractDay(value) {
    const match = String(value || "").match(/\d{4}-\d{2}-\d{2}/);
    return match ? match[0] : "";
  }

  function daysSince(day, now) {
    const current = extractDay(localDateKey(now));
    const target = extractDay(day);
    if (!current || !target) return null;
    const a = new Date(`${target}T00:00:00`);
    const b = new Date(`${current}T00:00:00`);
    const diff = Math.floor((b - a) / 86400000);
    return Number.isFinite(diff) ? Math.max(0, diff) : null;
  }

  function filterItems(items, filters, now) {
    const f = filters || {};
    const query = String(f.query || "").trim().toLocaleLowerCase();
    const company = String(f.company || "").trim().toLocaleLowerCase();
    const days = Number(f.days || 0);
    return (items || []).filter((item) => {
      if (f.kind && item.kind !== f.kind) return false;
      if (f.layer && item.layer !== f.layer) return false;
      if (f.space && item.space !== f.space) return false;
      if (company && !String(item.company || "").toLocaleLowerCase().includes(company)) return false;
      if (query) {
        const haystack = [item.line, item.title, item.source, item.company, item.page,
          item.section, item.sub, item.day].join(" ").toLocaleLowerCase();
        if (!haystack.includes(query)) return false;
      }
      if (days && (item.day == null || daysSince(item.day, now) == null || daysSince(item.day, now) > days)) return false;
      return true;
    });
  }

  function isStale(latest, now) {
    const day = extractDay(latest);
    return !day || day !== localDateKey(now);
  }

  return { localDateKey, extractDay, daysSince, filterItems, isStale };
});
