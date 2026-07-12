import random
import numpy as np
from copy import deepcopy
from quant_env.backtest.engine import BacktestEngine
from quant_env.analysis.performance import compute_metrics

class GeneticOptimizer:
    def __init__(self, data, strategy_class, param_space, pop_size=50, gens=10, mut_rate=0.2, capital=10000):
        self.data = data
        self.strategy_class = strategy_class
        self.param_space = param_space
        self.pop_size = pop_size
        self.generations = gens
        self.mut_rate = mut_rate
        self.capital = capital

    def _random_params(self):
        params = {}
        for p, (low,high,step) in self.param_space.items():
            if isinstance(step, int) or step == int(step):
                params[p] = random.randint(low, high)
            else:
                values = np.arange(low, high+step, step)
                params[p] = random.choice(values)
        return params

    def _fitness(self, params):
        eng = BacktestEngine(self.data.copy(), self.strategy_class, self.capital, **params)
        res = eng.run()
        return compute_metrics(res.fills_df, res.equity_df).get('sharpe_ratio', -999)

    def _crossover(self, p1, p2):
        child = {}
        for k in p1:
            child[k] = p1[k] if random.random()<0.5 else p2[k]
        return child

    def _mutate(self, ind):
        for p, (low,high,step) in self.param_space.items():
            if random.random() < self.mut_rate:
                if isinstance(step, int) or step == int(step):
                    ind[p] = random.randint(low, high)
                else:
                    ind[p] = random.choice(np.arange(low, high+step, step))
        return ind

    def run(self):
        pop = [self._random_params() for _ in range(self.pop_size)]
        best_fit = -np.inf
        best_params = None
        for gen in range(self.generations):
            fits = [self._fitness(ind) for ind in pop]
            max_fit, idx = max((f,i) for i,f in enumerate(fits))
            if max_fit > best_fit:
                best_fit = max_fit; best_params = deepcopy(pop[idx])
            print(f"Gen {gen}: best {max_fit:.3f} params {pop[idx]}")
            new_pop = []
            for _ in range(self.pop_size):
                a,b = random.sample(range(self.pop_size),2)
                p1 = pop[a] if fits[a]>fits[b] else pop[b]
                c,d = random.sample(range(self.pop_size),2)
                p2 = pop[c] if fits[c]>fits[d] else pop[d]
                child = self._crossover(p1,p2) if random.random()<0.7 else deepcopy(p1)
                child = self._mutate(child)
                new_pop.append(child)
            pop = new_pop
        return best_params, best_fit
