import json
from decimal import Decimal as D
from pathlib import Path
import pytest
from nba_combo_pricing.backtest import Trade,replay,cash_required,affordable_units
from nba_combo_pricing.calibration import summarize,freeze_method
from nba_combo_pricing.references import remove_margin,validated_midpoint

ROOT=Path(__file__).resolve().parents[1]


def example(**updates):
    row=json.loads((ROOT/'examples/illustrative_trades.jsonl').read_text().splitlines()[0]);row.update(updates)
    return Trade.from_dict(row)


def test_one_game_cap_is_shared_across_families():
    trades=[example(trade_id='a',contracts='1000'),example(trade_id='b',family='spread × total',contracts='1000')]
    result=replay(trades,premium_cents=3)
    assert sum(f['cost_including_fees'] for f in result['fills'])<=D(500)
    assert result['fills'][0]['resized']


def test_ties_are_not_assumed_fills():
    assert replay([example(fair_yes=.3,trade_yes=.33)],premium_cents=3)['competitive_prints']==0


def test_timestamp_sorting_uses_instants_not_strings():
    early=example(trade_id='early',contracts='1000',trade_time_utc='2026-01-01T01:00:00+01:00')
    late=example(trade_id='late',contracts='1000',trade_time_utc='2026-01-01T00:30:00Z')
    assert replay([late,early],premium_cents=3)['fills'][0]['trade_id']=='early'


def test_cash_rounding_and_maximal_affordable_quantity():
    assert cash_required(D('.3'),10000,D('.0175'),D('.01'))==D('70.37')
    n=affordable_units(D('.3'),100000,D(500),D('.0175'),D('.01'))
    assert cash_required(D('.3'),n,D('.0175'),D('.01'))<=500
    assert cash_required(D('.3'),n+1,D('.0175'),D('.01'))>500


def test_no_duplicate_trade_ids():
    with pytest.raises(ValueError,match='Duplicate'):replay([example(),example()],premium_cents=3)


def test_binary_payout_float_is_supported_without_truncating_other_values():
    result=replay([example(payout_yes=1.0)],premium_cents=3)
    assert result['net_pnl_usd']==-result['fills'][0]['cost_including_fees']
    with pytest.raises(ValueError,match='settlement'):example(payout_yes=.2)


def test_reference_requires_strict_prior_timestamp():
    with pytest.raises(ValueError,match='precede'):
        validated_midpoint(bid=.4,ask=.5,observed_at='2026-01-01T00:00:00Z',request_at='2026-01-01T00:00:00Z')
    result=validated_midpoint(bid=.4,ask=.5,observed_at='2026-01-01T00:00:00Z',request_at='2026-01-01T00:00:10Z')
    assert result['yes']==pytest.approx(.45)


def test_margin_removal_is_symmetric_and_outcome_free():
    for method in ['proportional','additive','power']:
        p=remove_margin([1.15,5.5],method)
        reverse=remove_margin([5.5,1.15],method)
        assert sum(p)==pytest.approx(1)
        assert p==pytest.approx(reverse[::-1])
    assert remove_margin([1.15,5.5],'power')[0]>remove_margin([1.15,5.5],'proportional')[0]


def test_calibration_resamples_games_not_trade_rows():
    records=[dict(game_id=str(i),probability=.5,outcome=i%2) for i in range(10)]
    first=summarize(records,draws=300);second=summarize(records+records,draws=300)
    assert first['games']==second['games']==10
    assert first['no_error_ci_low']==pytest.approx(second['no_error_ci_low'])
    assert first['no_error_ci_high']==pytest.approx(second['no_error_ci_high'])


def test_method_selection_never_reads_later_labels():
    earlier=[dict(date='2026-01-01',game_id='a',outcome=1,predictions=dict(proportional=.2,additive=.3,power=.4))]
    # Deliberately omit later labels and predictions: neither may be inspected.
    later=[dict(date='2026-03-01',game_id='b')]
    result=freeze_method(earlier+later,training_end_date='2026-02-01')
    assert result['selected_method']=='power' and result['training_cases']==1
