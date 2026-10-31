// The "had no sale" line under the "Above SSM's 3-week rule" list
// (GET /dashboard/stock-detail, 2026-10-24). A product with no sale in the
// window has all of its stock above the rule: above_rule_pesos = its stock
// pesos (backend/marts.stock_detail: max(pesos - weeks x 0, 0)). The list
// shows only above_rule_pesos > 0, so a no-sale product whose stock pesos are
// 0 (or below, clipped to 0) or not recorded (above_rule_pesos null) is in
// the count but not in the list. The line says how many of each, counted
// from the rows, so the count and the list reconcile.
//
// stock pesos = the count's valuation, else quantity x unit cost per case
// (migration 0041, mart.inventory_mart); a 0 can be a zero quantity, a zero
// valuation or a zero cost, which the response does not tell apart, so the
// line says "valued at ₱0", not why.
const plural = (n, one, many) => `${n.toLocaleString()} ${n === 1 ? one : many}`;

export const noSaleNote = (items = []) => {
  const noSale = (items || []).filter((r) => r?.no_sale_in_window);
  if (noSale.length === 0) return null;
  const listed = noSale.filter((r) => r.above_rule_pesos > 0).length;
  const zero = noSale.filter((r) => r.above_rule_pesos != null && !(r.above_rule_pesos > 0) && r.pesos === 0).length;
  const negative = noSale.filter((r) => r.above_rule_pesos != null && !(r.above_rule_pesos > 0) && r.pesos != null && r.pesos < 0).length;
  const unvalued = noSale.length - listed - zero - negative;
  const head = `${plural(noSale.length, 'product', 'products')} had no sale in those months, so all of their stock `
    + 'counts as above the rule';
  const left = [
    zero ? `${zero.toLocaleString()} valued at ₱0 at the count` : null,
    negative ? `${negative.toLocaleString()} valued below ₱0 at the count` : null,
    unvalued ? `${unvalued.toLocaleString()} with no stock value recorded` : null,
  ].filter(Boolean);
  if (left.length === 0) return `${head}.`;
  return `${head}: ${listed.toLocaleString()} listed · ${left.join(' · ')}, so nothing above the rule to list.`;
};
