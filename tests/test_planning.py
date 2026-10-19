"""Plan JSON storage and drift against a portfolio snapshot."""

from planning.model import Plan, Slice, allocation_drift, new_plan, parse_money, slice_errors
from planning.store import PlanStore


def test_parse_money():
    assert parse_money("$1,243,000") == 1_243_000
    assert parse_money("12345.67") == 12345.67
    assert parse_money("+$258.50") == 258.50
    assert parse_money("n/a") is None


def test_create_roundtrip_and_single_active(tmp_path):
    store = PlanStore(tmp_path)
    first = store.create("Core portfolio")
    second = store.create("Core portfolio")
    assert first.id == "core-portfolio"
    assert second.id == "core-portfolio-2"
    assert store.load(first.id).name == "Core portfolio"

    second.status = "active"
    store.save(second, make_active=True)
    first.status = "active"
    store.save(first, make_active=True)

    assert store.load(first.id).status == "active"
    assert store.load(second.id).status == "draft"
    assert [plan.id for plan in store.list_plans()][0] == first.id

    store.delete(second.id)
    assert store.load(second.id) is None


def test_slice_errors():
    rows = [Slice("Cash", 30, 10, 20)]
    assert any("floor and ceiling" in message for message in slice_errors(rows, "Sleeves"))


def test_drift_tags_cash_and_fill_next():
    plan = new_plan("Core", "core")
    plan.rebalance_band_pct = 5
    plan.classifications = {
        "AAPL": {"bucket": "Developed global equity", "sector": "Technology"},
        "RELIANCE": {"bucket": "Local equity", "sector": "Energy"},
    }
    positions = [
        {"symbol": "AAPL", "market_value": 350},
        {"symbol": "RELIANCE", "market_value": 300},
        {"symbol": "UNTAGGED", "market_value": 50},
    ]
    summary = {"Net liquidation": "$1,000"}
    drift = allocation_drift(plan, positions, summary)

    by_name = {row["name"]: row for row in drift["rows"]}
    assert drift["nav"] == 1000
    assert drift["cash"] == 300
    assert by_name["Cash"]["actual"] == 30
    assert by_name["Cash"]["status"] == "above ceiling"
    assert by_name["Developed global equity"]["actual"] == 35
    assert by_name["Developed global equity"]["invested"] == 350
    assert by_name["Developed global equity"]["target_value"] == 350
    assert by_name["Cash"]["invested"] == 300
    assert drift["invested"] == 650
    assert drift["outside"] == 50
    assert by_name["Developed global equity"]["status"] == "in band"
    assert by_name["Local equity"]["actual"] == 30
    assert "Emerging equity" in drift["fill_next"]
    assert drift["unclassified"] == ["UNTAGGED"]

    sectors = {row["name"]: row for row in drift["sectors"]}
    assert sectors["Technology"]["actual"] == 350 / 650 * 100
    assert any(row["symbol"] == "AAPL" and row["over_cap"] for row in drift["names"])


def test_weights_use_holdings_when_nav_missing():
    plan = Plan(id="x", name="X", buckets=[Slice("Cash", 10, 5, 20), Slice("Local equity", 90, 80, 100)])
    plan.classifications = {"TCS": {"bucket": "Local equity", "sector": "Technology"}}
    drift = allocation_drift(plan, [{"symbol": "TCS", "qty": 2, "market_price": 50}], {})
    assert drift["basis"] == "holdings"
    assert drift["cash"] is None
    by_name = {row["name"]: row for row in drift["rows"]}
    assert by_name["Local equity"]["actual"] == 100
    assert by_name["Cash"]["actual"] is None
