from decimal import Decimal

from lilith.sculpting import FeatureSculptor, SculptorPolicy, TradeObservation
from lilith.sizing import PositionSizingResearch, SizingObservation


def test_feature_combination_requires_evidence_and_stability():
    rows = []
    for index in range(40):
        rows.append(
            TradeObservation(
                trade_id=str(index),
                net_pnl=Decimal("2") if index % 4 else Decimal("-1"),
                r_multiple=Decimal("0.5") if index % 4 else Decimal("-0.25"),
                features={"session": "NEW_YORK", "regime": "TREND"},
            )
        )

    policy = SculptorPolicy(
        minimum_sample=30,
        minimum_expectancy_r=Decimal("0.05"),
        minimum_profit_factor=Decimal("1.10"),
        maximum_drawdown=Decimal("10"),
        minimum_stability_score=0.60,
    )
    results = FeatureSculptor(policy).analyse(rows)
    target = next(item for item in results if item.fingerprint == "regime=TREND|session=NEW_YORK")

    assert target.approved is True
    assert target.sample_size == 40
    assert target.expectancy_r > 0
    assert target.profit_factor > 1


def test_feature_combination_rejected_for_small_sample():
    rows = [
        TradeObservation(str(index), Decimal("1"), Decimal("0.2"), {"session": "LONDON"})
        for index in range(10)
    ]
    result = FeatureSculptor().analyse(rows)[0]
    assert result.approved is False
    assert "minimum_sample" in result.rejection_reasons


def test_position_sizing_research_is_counterfactual():
    rows = [
        SizingObservation(str(index), Decimal("1") if index % 2 else Decimal("-0.5"), Decimal("0.8"), Decimal("1.2"))
        for index in range(20)
    ]
    results = PositionSizingResearch().compare(rows, starting_equity=Decimal("100"))
    assert {item.policy for item in results} == {"fixed_risk", "confidence_scaled", "volatility_scaled"}
    assert all(item.final_equity > 0 for item in results)
