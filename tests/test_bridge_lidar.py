"""The deck top read from one window of LiDAR returns (bridge_lidar.deck_top): the deck, not the water under it, a lamp post on it or the
cars on it."""
import numpy as np

from urbanstyle.bridge_lidar import MIN_PTS, deck_top


def test_deck_top_is_the_deck():
    rng = np.random.default_rng(0)
    deck = 40.0 + rng.normal(0, 0.03, 3000)              # the road surface, 40 m up
    cars = 41.5 + rng.normal(0, 0.3, 300)                # cars on it
    water = -1.0 + rng.normal(0, 0.05, 200)              # the water seen past the deck's edge
    lamp = 45.5 + rng.normal(0, 0.2, 40)                 # a lamp post on the deck, more than 2 m above it
    assert abs(deck_top(np.concatenate([deck, cars, water, lamp])) - 40.0) < 0.1
    assert abs(deck_top(deck) - 40.0) < 0.1               # at grade: one cluster
    assert deck_top(deck[:MIN_PTS - 1]) is None           # too few returns: no measurement
