// ABC page, "Do the top sellers have enough stock?": how long a status's bar
// is (2026-11-06). The bar is the status's share of sales on one fixed 0-100%
// scale, so a 21% share fills 21% of the track whatever the product count.
// It used to be the product count against the largest count, which drew 48
// products (21% of sales) as half the track beside a "21%" label.
//
// `sharePct` is a percentage (21.3 for 21.3%), as the page sums GET /abc's
// revPct. Not normalised to the largest bar and no minimum width, so a small
// share is never drawn bigger than it is; out-of-range or missing values are
// held to the scale (0 to 100).
export const shareBarWidth = (sharePct) => {
  const value = Number(sharePct);
  if (!Number.isFinite(value) || value <= 0) return 0;
  return Math.min(value, 100);
};

export default shareBarWidth;
