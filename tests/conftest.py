import pytest
from backtesting.test import GOOG

from workbench import db

# A hand-written strategy that follows the contract: one Strategy subclass,
# tunable values as int/float/bool class attributes.
SMA_CODE = '''
from backtesting import Strategy
from backtesting.lib import crossover
from backtesting.test import SMA


class SmaCross(Strategy):
    n1 = 10
    n2 = 20
    use_exit = True
    stop_pct = 0.0
    _private = 5

    def init(self):
        self.a = self.I(SMA, self.data.Close, self.n1)
        self.b = self.I(SMA, self.data.Close, self.n2)

    def next(self):
        if crossover(self.a, self.b):
            self.buy()
        elif crossover(self.b, self.a) and self.use_exit:
            self.position.close()
'''

MARKET = {"ticker": "GOOG", "interval": "1d", "start": "2004-08-19", "end": "2013-03-02",
          "cash": 100_000.0, "commission": 0.0}


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def goog():
    return GOOG.copy()
