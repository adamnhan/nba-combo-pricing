"""Market-anchored NBA combo pricing research."""
from .pricer import Leg, fit_marginals, normalize_rfq, price_combo, price_shared_paths
from .simulator import SimulationBatch, Simulator
from .state import GameState

__all__ = ["GameState", "Leg", "SimulationBatch", "Simulator", "fit_marginals",
           "normalize_rfq", "price_combo", "price_shared_paths"]
__version__ = "0.1.0"
