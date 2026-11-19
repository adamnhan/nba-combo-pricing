"""NO-maker historical price-comparison replay with one shared game cash cap."""
import argparse,json
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal as D,ROUND_CEILING
from functools import lru_cache
from pathlib import Path
from .references import utc_timestamp

CONTRACT_STEP=D('.01')
FEE_STEP=D('.000001')


@lru_cache(maxsize=64)
def price_grid(ranges):
    prices=set()
    for start,end,step in ranges:
        if not all(x.is_finite() for x in [start,end,step]) or not D(0)<=start<end<=D(1) or step<=0:raise ValueError("Invalid price range")
        value=start
        while value<=end:
            if 0<value<1:prices.add(value)
            value+=step
    if not prices:raise ValueError("Empty price grid")
    return tuple(sorted(prices))


def cash_required(yes_price,units,fee_rate,balance_step):
    quantity=units*CONTRACT_STEP
    fee=(fee_rate*quantity*yes_price*(1-yes_price)).quantize(FEE_STEP,rounding=ROUND_CEILING)
    return (quantity*(1-yes_price)+fee).quantize(balance_step,rounding=ROUND_CEILING)


def affordable_units(yes_price,requested,budget,fee_rate,balance_step):
    low,high=0,requested
    while low<high:
        middle=(low+high+1)//2
        if cash_required(yes_price,middle,fee_rate,balance_step)<=budget:low=middle
        else:high=middle-1
    return low


@dataclass(frozen=True)
class Trade:
    trade_id:str
    game_id:str
    family:str
    quarter:int
    trade_time_utc:str
    fair_yes:D
    trade_yes:D
    contracts:D
    payout_yes:int
    grid:tuple
    fee_rate:D
    balance_step:D

    def __post_init__(self):
        utc_timestamp(self.trade_time_utc)
        if not self.trade_id or not self.game_id or self.quarter<1:raise ValueError("Missing identity or period")
        if not self.fair_yes.is_finite() or not self.trade_yes.is_finite() or not 0<=self.fair_yes<=1 or not 0<self.trade_yes<1:raise ValueError("Invalid probability")
        if not self.contracts.is_finite() or self.contracts<=0 or self.contracts%CONTRACT_STEP:raise ValueError("Invalid quantity")
        if self.payout_yes not in (0,1) or not self.fee_rate.is_finite() or self.fee_rate<0 or self.balance_step not in (D('.01'),D('.0001')):raise ValueError("Invalid settlement or fee terms")
        if not self.grid or list(self.grid)!=sorted(set(self.grid)) or any(not 0<p<1 for p in self.grid):raise ValueError("Invalid quote grid")

    @classmethod
    def from_dict(cls,row):
        return cls(trade_id=row['trade_id'],game_id=str(row['game_id']),family=row['family'],
            quarter=int(row['quarter']),trade_time_utc=row['trade_time_utc'],fair_yes=D(str(row['fair_yes'])),
            trade_yes=D(str(row['trade_yes'])),contracts=D(str(row['contracts'])),payout_yes=row['payout_yes'],
            grid=price_grid(tuple(tuple(D(str(r[k])) for k in ['start','end','step']) for r in row['price_ranges'])),
            fee_rate=D(str(row['maker_fee_rate'])),balance_step=D(str(row['balance_step'])))


def replay(trades,*,premium_cents,game_cap=D(500)):
    premium=D(str(premium_cents))
    if not premium.is_finite() or premium<0:raise ValueError("Invalid premium")
    game_cap=D(str(game_cap))
    if not game_cap.is_finite() or game_cap<=0:raise ValueError("Invalid game cap")
    trades=list(trades)
    if len({r.trade_id for r in trades})!=len(trades):raise ValueError("Duplicate trade ID")
    reserved=defaultdict(D);fills=[];competitive=0
    for r in sorted(trades,key=lambda r:(utc_timestamp(r.trade_time_utc),r.trade_id)):
        i=bisect_left(r.grid,r.fair_yes+premium/100)
        if i==len(r.grid) or r.grid[i]>=r.trade_yes:continue
        competitive+=1;quote=r.grid[i];units=int(r.contracts/CONTRACT_STEP)
        size=affordable_units(quote,units,game_cap-reserved[r.game_id],r.fee_rate,r.balance_step)
        if not size:continue
        quantity=size*CONTRACT_STEP;cost=cash_required(quote,size,r.fee_rate,r.balance_step)
        reserved[r.game_id]+=cost
        fills.append(dict(trade_id=r.trade_id,game_id=r.game_id,family=r.family,quarter=r.quarter,
            contracts=quantity,quote_yes=quote,quote_no=1-quote,cost_including_fees=cost,
            fees_and_rounding=cost-quantity*(1-quote),net_pnl_usd=quantity*(1-int(r.payout_yes))-cost,
            expected_net_usd=quantity*(1-r.fair_yes)-cost,resized=size<units))
    assert max(reserved.values(),default=D(0))<=game_cap
    return dict(competitive_prints=competitive,fills=fills,filled_games=len({f['game_id'] for f in fills}),
        net_pnl_usd=sum((f['net_pnl_usd'] for f in fills),D(0)),
        expected_net_usd=sum((f['expected_net_usd'] for f in fills),D(0)),
        fees_usd=sum((f['fees_and_rounding'] for f in fills),D(0)))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path);p.add_argument('--premium-cents',type=D,default=D(3));p.add_argument('--game-cap',type=D,default=D(500))
    a=p.parse_args();trades=[Trade.from_dict(json.loads(line)) for line in a.input.read_text().splitlines() if line.strip()]
    print(json.dumps(replay(trades,premium_cents=a.premium_cents,game_cap=a.game_cap),default=str,indent=2))


if __name__=='__main__':main()
