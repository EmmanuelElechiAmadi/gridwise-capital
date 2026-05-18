import pandas as pd
from datetime import datetime

class BacktestResult:
    def __init__(self):
        self.fills = []
        self.equity = []
        self.fills_df = None
        self.equity_df = None

class BacktestEngine:
    def __init__(self, data, strategy_class, initial_cash=10000, slippage=0.1, spread=0.3, **strategy_kwargs):
        self.data = data
        self.strategy_class = strategy_class
        self.cash = initial_cash
        self.inventory = 0.0
        self.result = BacktestResult()
        self.active_orders = {}
        self.slippage = slippage
        self.spread = spread
        self.kwargs = strategy_kwargs

    def run(self):
        from quant_env.strategies.grid_strategy import GridStrategy
        mock_con = MockConnector(self)
       
        # Simulate a tick from the first bar so the strategy can start
        first_bar = self.data.iloc[0]
        close_price = float(first_bar['close'])
        mock_con.tick = {'bid': close_price, 'ask': close_price}
        # Also update the connector's symbol_tick method to return it
        mock_con.symbol_tick = lambda: mock_con.tick
        
        strat = self.strategy_class(mock_con, mock_con.config, mock_con.logger)
        strat.on_start()
        for idx, bar in self.data.iterrows():
            high, low, close = bar['high'], bar['low'], bar['close']
            filled = []
            for price, side in list(self.active_orders.items()):
                if low <= price <= high:
                    filled.append((price, side))
            for price, side in filled:
                del self.active_orders[price]
                fill_price = price + (self.slippage + self.spread/2) if side=='buy' else price - (self.slippage + self.spread/2)
                if side == 'buy':
                    self.cash -= fill_price * strat.lot
                    self.inventory += strat.lot
                else:
                    self.cash += fill_price * strat.lot
                    self.inventory -= strat.lot
                self.result.fills.append({'timestamp': idx, 'side': side, 'price': fill_price, 'volume': strat.lot})
          
            eq = self.cash + self.inventory * close
            self.result.equity.append((idx, eq))    

        # ---- Close any remaining inventory at the last bar ----
        if self.inventory != 0:
            final_bar = self.data.iloc[-1]
            final_close = float(final_bar['close'])
            if self.inventory > 0:
                side = 'sell'
                fill_price = final_close - (self.slippage + self.spread / 2)
            else:
                side = 'buy'
                fill_price = final_close + (self.slippage + self.spread / 2)
            volume = abs(self.inventory)
            if side == 'sell':
                self.cash += fill_price * volume
            else:
                self.cash -= fill_price * volume
            self.inventory = 0.0
            self.result.fills.append({
                'timestamp': self.data.index[-1],
                'side': side,
                'price': fill_price,
                'volume': volume
            })
            final_eq = self.cash
            self.result.equity.append((self.data.index[-1], final_eq))

        self.result.fills_df = pd.DataFrame(self.result.fills)
        self.result.equity_df = pd.DataFrame(self.result.equity, columns=['timestamp','equity'])
        return self.result

class MockConnector:
    def __init__(self, engine):
        self.engine = engine
        self.config = type('obj',(),{'SYMBOL':'BACKTEST','LOT_SIZE':engine.kwargs.get('lot',0.01),
            'GRID_SPACING':engine.kwargs.get('spacing',0.1),'NUM_LEVELS':engine.kwargs.get('levels',5)})
        self.logger = type('obj',(),{'info':print})
    def symbol_tick(self): return None
    def place_limit_order(self, order_type, price, volume):
        side = 'buy' if 'buy' in order_type else 'sell'
        self.engine.active_orders[price] = side
        return True
    def get_open_orders(self): return []
