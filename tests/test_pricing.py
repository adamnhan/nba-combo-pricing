import hashlib,json
from dataclasses import replace
from pathlib import Path
import numpy as np
import pytest
from nba_combo_pricing import GameState,Leg,SimulationBatch,fit_marginals,price_shared_paths
from nba_combo_pricing.pricer import MODEL_SHA256,impossible_combo

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def state():return GameState.from_dict(json.loads((ROOT/'examples/illustrative_rfq.json').read_text())['state'])


def batch(state,counts):
    scores=np.repeat(np.array([[120,110],[100,95],[110,120],[95,100]]),counts,axis=0)
    n=len(scores);minutes=np.ones((n,len(state.players)))*100
    return SimulationBatch(state.players,scores,np.zeros((n,len(state.players),4),dtype=int),minutes,minutes,np.zeros(n,dtype=int))


def legs():
    return (Leg('home','illustrative-game','moneyline','yes',1,1),Leg('total','illustrative-game','total','yes',221,None))


def test_market_anchoring_preserves_two_by_two_dependence():
    hits=np.repeat(np.array([[1,1],[1,0],[0,1],[0,0]],bool),[40,10,10,40],axis=0)
    q=fit_marginals(hits,np.array([.6,.55]));cells=np.array([q,.6-q,.55-q,1-.6-.55+q])
    assert cells.min()>0
    assert cells[0]*cells[3]/(cells[1]*cells[2])==pytest.approx(16,rel=2e-5)
    assert cells[[0,1]].sum()==pytest.approx(.6)


def test_independent_paths_reproduce_product():
    hits=np.array([[1,1],[1,0],[0,1],[0,0]],bool)
    assert fit_marginals(hits,np.array([.75,.6]))==pytest.approx(.45,abs=1e-7)


def test_seed_disagreement_rejects_a_quote(state):
    a,b=batch(state,[45,5,5,45]),batch(state,[5,45,45,5])
    result=price_shared_paths(state,legs(),[a,b],{'home':.5,'total':.5})
    assert result['anchor_status']=='split_seed_disagreement'
    assert result['anchored_yes'] is None


def test_impossible_moneylines_settle_to_zero(state):
    ls=(legs()[0],Leg('away',state.game_id,'moneyline','yes',1,2))
    result=price_shared_paths(state,ls,[batch(state,[5,5,5,5])]*2,{'home':.6,'away':.4})
    assert result['anchor_status']=='exact' and result['anchored_yes']==0


def test_player_points_threes_contradiction(state):
    stats=list(state.stats);stats[0]=(0,0,0,0,0);state=replace(state,stats=tuple(stats))
    ls=(Leg('points',state.game_id,'points','no',10,state.players[0]),Leg('threes',state.game_id,'threes','yes',4,state.players[0]))
    assert impossible_combo(state,ls)


def test_possible_dnp_is_not_silently_a_binary_quote(state):
    stats=list(state.stats);stats[0]=(0,0,0,0,0);played=list(state.seconds_played);played[0]=0
    state=replace(state,stats=tuple(stats),seconds_played=tuple(played))
    b=batch(state,[5,5,5,5]);b.seconds_played[:,0]=0
    leg=Leg('points',state.game_id,'points','yes',1,state.players[0])
    result=price_shared_paths(state,[leg],[b,b],{'points':.5})
    assert result['anchor_status']=='possible_nonbinary_leg_payout'


def test_frozen_model_artifact():
    assert hashlib.sha256((ROOT/'models/fitted_model.npz').read_bytes()).hexdigest()==MODEL_SHA256
