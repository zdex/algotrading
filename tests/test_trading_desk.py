"""Trading desk: agreed signals queue a paper order, and the roster reports who is running."""

from agents.agno.trading_desk import (
    AGENT_NAMES,
    DeskCompany,
    FundamentalPacket,
    Signal,
    SocialPacket,
    TechnicalPacket,
    TradingDesk,
    WebPacket,
    combine_signals,
    load_orders,
    score_technical,
)


def _company() -> DeskCompany:
    return DeskCompany("AAPL", "Apple", "Information Technology")


def _bullish_web(_company: DeskCompany) -> WebPacket:
    return WebPacket(headlines=["strong beat surge healthy demand"])


def _bullish_fundamental(_company: DeskCompany) -> FundamentalPacket:
    return FundamentalPacket(
        documents=["10-Q period 2026-06-30 filed 2026-08-01 (SEC EDGAR)"],
        text="quarterly report revenue growth earnings beat margin expansion cash flow",
        excerpt_found=True,
    )


def _bullish_social(_company: DeskCompany) -> SocialPacket:
    return SocialPacket(posts=["@desk: strong beat"], scores=[0.6, 0.4])


def _range_technical(_company: DeskCompany) -> TechnicalPacket:
    return TechnicalPacket(brief="Price action: range.", trend="range", breakout="none", bars=80, last_close=100.0)


def _bullish_technical(_company: DeskCompany) -> TechnicalPacket:
    return TechnicalPacket(
        brief="Uptrend and close above the prior range.",
        trend="uptrend",
        breakout="above_prior_range",
        last_close=110.0,
        support=100.0,
        resistance=120.0,
        gap_pct=0.8,
        volume_vs_average=1.5,
        bars=120,
    )


def _bearish_technical(_company: DeskCompany) -> TechnicalPacket:
    return TechnicalPacket(
        brief="Downtrend and close below the prior range.",
        trend="downtrend",
        breakout="below_prior_range",
        last_close=90.0,
        gap_pct=-0.8,
        volume_vs_average=1.4,
        bars=90,
    )


def _bearish_fundamental(_company: DeskCompany) -> FundamentalPacket:
    return FundamentalPacket(
        documents=["10-Q period 2026-06-30 filed 2026-08-01 (SEC EDGAR)"],
        text="margin pressure guidance cut demand slowdown revenue miss",
        excerpt_found=True,
    )


def test_three_sources_agree_and_queue_a_paper_order(tmp_path):
    path = tmp_path / "orders.json"
    running = []

    def on_update(state):
        running.append(tuple(name for name in AGENT_NAMES if state.roster[name] == "running"))

    desk = TradingDesk(_bullish_web, _bullish_fundamental, _bullish_social, _range_technical, orders_path=path)
    state = desk.run([_company()], on_update=on_update)
    decision = state.decisions[0]
    assert decision.action == "buy"
    assert decision.qty == 15
    assert state.orders[0].side == "BUY"
    assert state.orders[0].qty == 15
    assert state.orders[0].status == "queued"
    assert state.orders[0].route == "paper blotter"
    assert "not sent to a broker" in state.log[-1].text
    assert ("Web agent", "Fundamental agent", "Social agent", "Technical agent") in running
    assert any("Web signal agent" in snapshot for snapshot in running)
    assert any("Technical signal agent" in snapshot for snapshot in running)
    assert ("Decision agent",) in running
    assert ("Execution agent",) in running
    assert {line.agent for line in state.log} == set(AGENT_NAMES)
    saved = load_orders(path)
    assert saved[0]["symbol"] == "AAPL"
    assert saved[0]["side"] == "BUY"


def test_opposing_sources_do_not_trade(tmp_path):
    desk = TradingDesk(
        _bullish_web, _bearish_fundamental, _bullish_social, _range_technical,
        orders_path=tmp_path / "orders.json",
    )
    state = desk.run([_company()])
    assert state.decisions[0].action == "hold"
    assert state.orders == []
    assert "No order" in state.log[-1].text
    assert load_orders(tmp_path / "orders.json") == []


def test_one_source_is_not_enough_to_trade():
    desk = TradingDesk(
        _bullish_web,
        lambda _company: FundamentalPacket(error="No SEC company record."),
        lambda _company: SocialPacket(error="Social lookup skipped: set X_BEARER_TOKEN to read posts from X."),
        _range_technical,
    )
    state = desk.run([_company()])
    assert state.decisions[0].action == "hold"
    assert state.orders == []
    assert state.roster["Fundamental agent"] == "error"
    assert state.roster["Social agent"] == "error"
    assert state.roster["Execution agent"] == "done"


def test_a_failing_collector_is_reported_and_the_desk_finishes():
    def boom(_company: DeskCompany) -> WebPacket:
        raise RuntimeError("network down")

    desk = TradingDesk(boom, _bullish_fundamental, _bullish_social, _range_technical)
    state = desk.run([_company()])
    assert state.roster["Web agent"] == "error"
    assert "network down" in next(line.text for line in state.log if line.agent == "Web agent")
    assert state.decisions[0].action == "buy"
    assert state.orders[0].qty == 10


def test_technical_breakout_joins_a_buy(tmp_path):
    score, points = score_technical(_bullish_technical(_company()))
    assert score == 1.0
    assert any("uptrend" in point for point in points)
    desk = TradingDesk(
        lambda _company: WebPacket(error="No recent news items found."),
        lambda _company: FundamentalPacket(error="No SEC company record."),
        _bullish_social,
        _bullish_technical,
        orders_path=tmp_path / "orders.json",
    )
    state = desk.run([_company()])
    technical = next(signal for signal in state.signals if signal.agent == "Technical signal agent")
    assert technical.stance == "buy"
    assert state.roster["Technical agent"] == "done"
    assert "Uptrend" in next(line.text for line in state.log if line.agent == "Technical agent")
    assert state.decisions[0].action == "buy"
    assert state.decisions[0].qty == 10


def test_technical_opposition_blocks_the_trade():
    desk = TradingDesk(
        _bullish_web,
        lambda _company: FundamentalPacket(error="No SEC company record."),
        _bullish_social,
        _bearish_technical,
    )
    state = desk.run([_company()])
    technical = next(signal for signal in state.signals if signal.agent == "Technical signal agent")
    assert technical.stance == "sell"
    assert state.decisions[0].action == "hold"
    assert state.orders == []


def test_desk_runs_on_langgraph():
    from langgraph.graph.state import CompiledStateGraph

    desk = TradingDesk(_bullish_web, _bullish_fundamental, _bullish_social, _range_technical)
    assert isinstance(desk.graph, CompiledStateGraph)
    assert set(AGENT_NAMES) <= set(desk.graph.nodes)


def test_combine_signals_names_the_votes():
    signals = [
        Signal("Web signal agent", "AAPL", "buy", 0.4, "web"),
        Signal("Fundamental signal agent", "AAPL", "flat", 0.0, "flat"),
        Signal("Social signal agent", "AAPL", "sell", -0.3, "social"),
    ]
    action, qty, reason = combine_signals(signals)
    assert action == "hold"
    assert qty == 0
    assert "do not agree" in reason


def test_schedule_labels_and_triggers():
    from datetime import time, timedelta

    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    from agents.agno.schedule import DeskSchedule, trigger_for

    interval = DeskSchedule(every_minutes=15)
    assert interval.label() == "every 15 minutes"
    assert DeskSchedule(every_minutes=60).label() == "every 1 hour"
    daily = DeskSchedule(every_minutes=None, daily_at=time(9, 30))
    assert daily.label() == "daily at 09:30"
    monthly = DeskSchedule(every_minutes=None, daily_at=time(9, 30), cadence="monthly")
    assert monthly.label() == "monthly on day 1 at 09:30"
    quarterly = DeskSchedule(every_minutes=None, daily_at=time(16, 15), cadence="quarterly")
    assert quarterly.label() == "quarterly on day 1 (Jan, Apr, Jul, Oct) at 16:15"
    assert isinstance(trigger_for(interval), IntervalTrigger)
    assert trigger_for(interval).interval == timedelta(minutes=15)
    cron = trigger_for(daily)
    assert isinstance(cron, CronTrigger)
    assert "hour='9'" in str(cron) and "minute='30'" in str(cron)
    monthly_cron = str(trigger_for(monthly))
    assert "day='1'" in monthly_cron and "hour='9'" in monthly_cron and "minute='30'" in monthly_cron
    quarterly_cron = str(trigger_for(quarterly))
    assert "month='1,4,7,10'" in quarterly_cron and "day='1'" in quarterly_cron
    assert "hour='16'" in quarterly_cron and "minute='15'" in quarterly_cron


def test_scheduled_runner_keeps_a_future_run_and_can_stop(tmp_path):
    from datetime import datetime, timedelta

    from agents.agno.schedule import DeskSchedule, ScheduledRunner

    def factory():
        return TradingDesk(_bullish_web, _bullish_fundamental, _bullish_social, _range_technical, orders_path=tmp_path / "orders.json")

    runner = ScheduledRunner(
        [_company()],
        DeskSchedule(every_minutes=15),
        orders_path=tmp_path / "orders.json",
        desk_factory=factory,
    )
    runner.start(immediate=False)
    try:
        nxt = runner.next_run_at()
        assert nxt is not None
        assert nxt > datetime.now().astimezone() + timedelta(minutes=10)
        runner.run_once()
        view = runner.view()
        assert view["run_count"] == 1
        assert view["latest"]["decisions"][0]["action"] == "buy"
        assert view["symbols"] == ["AAPL"]
        assert view["schedule"] == "every 15 minutes"
    finally:
        runner.stop()
    assert runner.active is False
    assert runner.next_run_at() is None


def test_two_agents_can_be_scheduled_together(tmp_path):
    from agents.agno.schedule import DeskSchedule, ScheduledRunner

    def factory():
        return TradingDesk(
            _bullish_web,
            _bullish_fundamental,
            _bullish_social,
            _range_technical,
            orders_path=tmp_path / "orders.json",
        )

    first = ScheduledRunner(
        [_company()],
        DeskSchedule(every_minutes=30),
        orders_path=tmp_path / "orders.json",
        desk_factory=factory,
        label="Agent 1",
    )
    second = ScheduledRunner(
        [DeskCompany("MSFT", "Microsoft", "Information Technology")],
        DeskSchedule(every_minutes=60),
        orders_path=tmp_path / "orders.json",
        desk_factory=factory,
        label="Agent 2",
    )
    first.start(immediate=False)
    second.start(immediate=False)
    try:
        assert first.active and second.active
        assert first.view()["label"] == "Agent 1"
        assert first.view()["symbols"] == ["AAPL"]
        assert second.view()["symbols"] == ["MSFT"]
        assert second.view()["schedule"] == "every 1 hour"
    finally:
        first.stop()
        second.stop()
    assert first.active is False
    assert second.active is False
