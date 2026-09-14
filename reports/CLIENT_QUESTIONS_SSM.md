# Questions for San San Marketing

*Prepared for Thea to relay. Plain business language — none of this needs any
technical knowledge, it's about how your warehouse and supplier arrangements
actually work. "We don't track that" is a useful answer too.*

We need six operational facts to finish the replenishment model. The first two are
the most important — they decide how the whole thing is timed.

---

## 1. How often do you decide on replenishment, and how long does delivery take?

- How often does the procurement team actually **review stock and place / accept an
  order** — weekly, every two weeks, monthly?
- Once you place an order with Unilever (or Del Monte), roughly **how many days
  until it's on your shelves**?

*→ a cadence (e.g. "weekly") and a number of days (e.g. "10–14 days")*

---

## 2. Supplier delivery limits

For the coming order cycle, **what is the most stock Unilever will deliver to
you**? And Del Monte? If you have the **annual allocation schedule** (the 52-week
plan) or a monthly/weekly quota document, a copy of that answers this completely.

*→ number of cases (or pieces), per supplier — or the schedule document*

---

## 3. Warehouse capacity

When your warehouse is **completely full**, roughly how much stock does it hold?
Use whatever unit is natural — total pallets, total cases, or "about X times a
normal delivery."

*→ one number*

---

## 4. Cost to hold stock

Approximately **what does it cost you per month to keep one case** of product
sitting in the warehouse?

If you don't track it that way: **what is your total monthly warehouse cost**
(rent, electricity, warehouse staff, insurance), and roughly **how many cases are
in the warehouse on an average day**? We'll divide.

*→ ₱ per case per month, or the two numbers to derive it*

---

## 5. What you pay your suppliers

Do you have a **current price list** of what you pay Unilever and Del Monte **per
case, by product**?

We can also read the price from your Stock-on-Hand report's "Last Purchase Price"
column — please **confirm that column is kept up to date**.

*→ ₱ per case by product, or confirmation the SOH column is current*

---

## 6. Ordering cost  *(only if easy to answer — otherwise skip)*

Roughly **what does it cost you in staff time and paperwork to place and receive
one purchase order**, regardless of how big it is?

*→ ₱ per order*

---

## Separately — a data issue in your Sell Out reports (heads-up, not blocking)

This isn't one of the six facts above — Del Monte isn't part of the active
model yet, so it doesn't hold anything up. But you should know about it.

In your **Sell Out** monthly reports (the ones with category/brand rows like
"/ACE/BASE", "/CRUSHED/BASE"), the **first column is sometimes showing the
text "False"** instead of a category name — across 2023 and early 2024
exports, about **194 rows** total. The sales figures on those rows look real
and correct; it's just the category label that's missing. This is almost
certainly a broken formula or lookup in the report template on your end, not
something that happened on our side — the row next to it, and every other
column, looks normal.

**Could someone check the Sell Out report template for a broken formula in
that leading column?** If you have a corrected export for those months, or
can tell us what those categories should have been, that would let us
recover the real breakdown — otherwise we'll keep the sales figures grouped
under "uncategorized" for that period, which is accurate but less useful
than the real category would be.

*→ either a corrected export, or confirmation of what's expected in that
column so we know what to look for going forward*

---

### Why we're asking

Your current rule — hold three weeks of safety stock for every product — ties up
an estimated ₱50–60M in slow-moving inventory while not reliably preventing
stockouts on the fast movers. The model we're building sets a **per-product**
reorder level from each product's own sales pattern. To do that within your real
constraints, it needs the six facts above. Everything else it computes from your
sales and stock history.
