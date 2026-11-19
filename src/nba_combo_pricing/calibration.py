"""Calibration with whole-game resampling and an explicit error convention."""
from collections import defaultdict
from datetime import date
import math
import numpy as np


def summarize(records, *, draws=4000, seed=20261119):
    """Rows: game_id, probability=YES, outcome=YES payout, optional weight.

    Positive NO overvaluation is observed YES minus predicted YES. Outcomes
    and forecasts are compared without treating repeated trades as games.
    """
    buckets = defaultdict(lambda: np.zeros(4))
    yes, no = False, False
    for r in records:
        p,y,w=float(r['probability']),float(r['outcome']),float(r.get('weight',1))
        if not all(math.isfinite(x) for x in [p,y,w]) or not 0<=p<=1 or y not in (0,1) or w<=0:
            raise ValueError("Invalid probability, outcome or weight")
        buckets[str(r['game_id'])] += [w,w*p,w*y,w*(p-y)**2]
        yes |= bool(y);no |= not bool(y)
    if not buckets:
        raise ValueError("Empty calibration sample")
    a=np.array([v for _,v in sorted(buckets.items())]);s=a.sum(axis=0)
    result=dict(games=len(a),weight=float(s[0]),predicted_yes=float(s[1]/s[0]),
        observed_yes=float(s[2]/s[0]),no_overvaluation_cents=float(100*(s[2]-s[1])/s[0]),
        yes_overprediction_cents=float(100*(s[1]-s[2])/s[0]),brier=float(s[3]/s[0]),
        equal_game_no_overvaluation_cents=float(np.mean(100*(a[:,2]-a[:,1])/a[:,0])),
        no_error_ci_low=None,no_error_ci_high=None)
    if len(a)>=5 and yes and no:
        rng=np.random.default_rng(seed);values=[]
        for start in range(0,draws,128):
            n=min(128,draws-start);b=a[rng.integers(0,len(a),(n,len(a)))].sum(axis=1)
            values.extend(100*(b[:,2]-b[:,1])/b[:,0])
        result['no_error_ci_low'],result['no_error_ci_high']=np.quantile(values,[.025,.975]).tolist()
    return result


def freeze_method(records, *, training_end_date, methods=('proportional','additive','power')):
    """Select minimum equal-game Brier on earlier common cases only.

    Each row supplies date, game_id, outcome and predictions keyed by method.
    Later rows are ignored before outcomes or predictions are inspected.
    """
    cutoff=date.fromisoformat(training_end_date)
    training=[r for r in records if date.fromisoformat(r['date'])<=cutoff]
    common=[r for r in training if all(m in r['predictions'] and r['predictions'][m] is not None for m in methods)]
    if not common:raise ValueError("No common training cases")
    scores={}
    for method in methods:
        games=defaultdict(list)
        for r in common:
            p=float(r['predictions'][method]);y=r['outcome']
            if not math.isfinite(p) or not 0<=p<=1 or y not in (0,1):raise ValueError("Invalid training prediction")
            games[r['game_id']].append((p-y)**2)
        scores[method]=float(np.mean([np.mean(x) for x in games.values()]))
    chosen=min(methods,key=lambda m:(scores[m],methods.index(m)))
    return dict(selected_method=chosen,training_end_date=training_end_date,
                training_cases=len(common),training_games=len({r['game_id'] for r in common}),scores=scores)
