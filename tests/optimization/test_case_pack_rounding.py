"""Case-pack rounding (analytics.optimization.lp.round_to_case_packs, wired into scripts.run_lp.plan_cycle):
orders go to whole packs INSIDE the warehouse and allocation ceilings, not after them."""
import pytest

from analytics.optimization.lp import SKUInput, constraint_slacks, round_to_case_packs
from scripts.run_lp import ProductInput, build_parser, plan_cycle


def sku(sku_id, demand=100.0, stock=0.0, principal="unilever", weight=1.0):
    # target 0, so need = demand - stock; only the orders below matter to the rounding
    return SKUInput(sku_id=sku_id, principal=principal, demand=demand, target_stock=0.0, stock_on_hand=stock,
                    safety_stock=0.0, procurement_cost_per_unit=1.0, storage_cost_per_unit=0.0, revenue_weight=weight)


BIG = 1e12


def test_no_pack_size_or_pack_of_one_is_unchanged():
    skus = [sku("a"), sku("b"), sku("c")]
    orders = {"a": 37.3, "b": 12.6, "c": 5.0}
    rounded, audit = round_to_case_packs(skus, orders, {"a": None, "b": 1.0}, BIG, {"unilever": BIG})
    assert rounded == orders
    assert [r["action"] for r in audit] == ["unchanged"] * 3
    assert [r["reason"] for r in audit] == ["no pack size", "pack size 1", "no pack size"]


def test_rounds_up_to_the_next_whole_pack_when_there_is_room():
    rounded, audit = round_to_case_packs([sku("a")], {"a": 37.3}, {"a": 12.0}, BIG, {"unilever": BIG})
    assert rounded["a"] == 48.0
    assert audit[0] == {"sku_id": "a", "pack_size": 12.0, "before": 37.3, "after": 48.0, "action": "rounded_up"}


def test_zero_and_whole_pack_orders_are_left_alone():
    skus = [sku("a"), sku("b")]
    rounded, audit = round_to_case_packs(skus, {"a": 0.0, "b": 36.0}, {"a": 12.0, "b": 12.0}, BIG, {"unilever": BIG})
    assert rounded == {"a": 0.0, "b": 36.0}
    assert [r["reason"] for r in audit] == ["order is 0", "already whole packs"]


def test_a_float_a_hair_off_a_whole_pack_is_still_whole():
    rounded, _ = round_to_case_packs([sku("a")], {"a": 36.0000000001}, {"a": 12.0}, BIG, {"unilever": BIG})
    assert rounded["a"] == 36.0


def test_round_up_that_would_breach_the_allocation_goes_down_instead():
    skus = [sku("a"), sku("b")]
    orders = {"a": 37.0, "b": 37.0}                       # 74 pieces; ceiling 74 leaves no room to round up
    rounded, audit = round_to_case_packs(skus, orders, {"a": 12.0, "b": 12.0}, BIG, {"unilever": 74.0})
    assert sum(rounded.values()) <= 74.0
    assert sorted(rounded.values()) == [36.0, 36.0]
    assert {r["action"] for r in audit} == {"rounded_down_at_ceiling"}


def test_room_for_only_some_roundups_goes_to_the_higher_revenue_weight_first():
    skus = [sku("low", weight=0.1), sku("high", weight=0.9)]
    orders = {"low": 37.0, "high": 37.0}                  # 74 pieces; ceiling 86 leaves room for one +11
    rounded, audit = round_to_case_packs(skus, orders, {"low": 12.0, "high": 12.0}, BIG, {"unilever": 86.0})
    assert rounded == {"low": 36.0, "high": 48.0}
    assert sum(rounded.values()) <= 86.0
    assert {r["sku_id"]: r["action"] for r in audit} == {"low": "rounded_down_at_ceiling", "high": "rounded_up"}


def test_the_warehouse_ceiling_counts_stock_on_hand_too():
    skus = [sku("a", stock=60.0)]
    rounded, _ = round_to_case_packs(skus, {"a": 37.0}, {"a": 12.0}, 60.0 + 40.0, {"unilever": BIG})
    assert rounded["a"] == 36.0                           # 48 would put 60 + 48 over 100
    rounded, _ = round_to_case_packs(skus, {"a": 37.0}, {"a": 12.0}, 60.0 + 48.0, {"unilever": BIG})
    assert rounded["a"] == 48.0                           # exactly at the ceiling is allowed


def test_each_principal_has_its_own_allocation():
    skus = [sku("u", principal="unilever"), sku("d", principal="delmonte")]
    rounded, _ = round_to_case_packs(skus, {"u": 37.0, "d": 37.0}, {"u": 12.0, "d": 12.0}, BIG,
                                     {"unilever": 37.0, "delmonte": 100.0})
    assert rounded == {"u": 36.0, "d": 48.0}


def test_the_result_never_breaks_a_ceiling_the_input_met():
    import random
    rng = random.Random(7)
    for trial in range(200):
        skus = [sku(f"s{i}", stock=rng.uniform(0, 50), principal=rng.choice(["unilever", "delmonte"]),
                    weight=rng.random()) for i in range(12)]
        orders = {s.sku_id: rng.uniform(0, 200) for s in skus}
        packs = {s.sku_id: rng.choice([None, 1.0, 6.0, 12.0, 24.0]) for s in skus}
        slack = {p: rng.uniform(0, 60) for p in ("unilever", "delmonte")}
        ceilings = {p: sum(orders[s.sku_id] for s in skus if s.principal == p) + slack[p] for p in slack}
        warehouse = sum(s.stock_on_hand for s in skus) + sum(orders.values()) + rng.uniform(0, 80)
        rounded, _ = round_to_case_packs(skus, orders, packs, warehouse, ceilings)
        after = constraint_slacks(skus, rounded, warehouse, ceilings)
        assert min(after.values()) >= -1e-6, (trial, after)
        for s in skus:
            pack = packs[s.sku_id]
            if pack is not None and pack > 1 and orders[s.sku_id] > 1e-6:
                assert rounded[s.sku_id] % pack == pytest.approx(0, abs=1e-6) or \
                    rounded[s.sku_id] % pack == pytest.approx(pack, abs=1e-6)
                assert abs(rounded[s.sku_id] - orders[s.sku_id]) < pack
            else:
                assert rounded[s.sku_id] == orders[s.sku_id]


def test_constraint_slacks_names_warehouse_and_each_allocation():
    skus = [sku("a", stock=10.0), sku("b", principal="delmonte")]
    slacks = constraint_slacks(skus, {"a": 20.0, "b": 5.0}, 100.0, {"unilever": 25.0, "delmonte": 5.0})
    assert slacks == {"warehouse": 100.0 - 10.0 - 25.0, "allocation:delmonte": 0.0, "allocation:unilever": 5.0}


# --- through plan_cycle ----------------------------------------------------------------------------------------

def _product(key, pack, forecast=1000.0):
    return ProductInput(product_key=key, sku_id=f"SKU{key}", principal="unilever", forecast=forecast, sigma_d=40.0,
                        stock_on_hand=0.0, in_stock_file=True, cost_per_piece=10.0, prior_year_pieces=50_000.0,
                        prior_year_revenue=100_000.0, pack_size=pack)


def test_plan_cycle_keeps_both_quantities_and_does_not_touch_need():
    products = [_product(1, 24.0), _product(2, None), _product(3, 1.0)]
    on = plan_cycle(products, build_parser().parse_args([]))
    off = plan_cycle(products, build_parser().parse_args(["--no-case-pack-rounding"]))
    assert off.orders_before_pack_rounding is None and off.pack_audit == []
    assert on.orders_before_pack_rounding == off.orders          # the solve is identical, rounding is after it
    assert [s.need for s in on.skus] == [s.need for s in off.skus]
    assert [s.safety_stock for s in on.skus] == [s.safety_stock for s in off.skus]
    assert on.orders["SKU1"] % 24.0 == 0.0
    assert on.orders["SKU2"] == off.orders["SKU2"] and on.orders["SKU3"] == off.orders["SKU3"]
    assert all(v >= -1e-9 for v in on.slacks_after_pack_rounding.values())
    assert on.slacks_before_pack_rounding.keys() == on.slacks_after_pack_rounding.keys()
    assert on.summary()["allocation_binds"]["unilever"] is False


def test_plan_cycle_rounds_inside_a_binding_allocation():
    products = [_product(i, 24.0) for i in range(1, 6)]
    plan = plan_cycle(products, build_parser().parse_args(["--allocation-pct", "10"]))
    ceiling = plan.allocation["unilever"]
    assert sum(plan.orders_before_pack_rounding.values()) == pytest.approx(ceiling, rel=1e-6)   # the LP used it all
    assert sum(plan.orders.values()) <= ceiling + 1e-6
    assert all(o % 24.0 == 0.0 for o in plan.orders.values())
    assert sum(plan.orders.values()) < ceiling - 0.5                    # rounding leaves it a few pieces under...
    assert plan.summary()["allocation_binds"]["unilever"] is True       # ...and the ceiling is still what cut the orders
