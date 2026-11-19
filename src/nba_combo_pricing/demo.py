"""Offline inference on a deliberately illustrative RFQ and game state."""
import argparse,hashlib,json,time
from pathlib import Path
from .pricer import Leg,MODEL_SHA256,price_combo
from .simulator import Simulator
from .state import GameState


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,default=Path('examples/illustrative_rfq.json'))
    p.add_argument('--model',type=Path,default=Path('models/fitted_model.npz'))
    p.add_argument('--paths-per-seed',type=int,default=4096)
    a=p.parse_args()
    if hashlib.sha256(a.model.read_bytes()).hexdigest()!=MODEL_SHA256:raise ValueError('Frozen artifact checksum mismatch')
    data=json.loads(a.input.read_text());state=GameState.from_dict(data['state'])
    legs=tuple(Leg(**r) for r in data['legs']);began=time.monotonic()
    result=price_combo(Simulator.load(a.model),state,legs,yes_midpoints=data['yes_midpoints'],paths_per_seed=a.paths_per_seed,seed=20261117)
    result.update(example='Illustrative state and reference probabilities; not a historical RFQ or performance measurement.',
                  independent_yes=data['yes_midpoints'][legs[0].ticker]*data['yes_midpoints'][legs[1].ticker],elapsed_seconds=round(time.monotonic()-began,3))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
