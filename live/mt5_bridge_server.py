import MetaTrader5 as mt5
from flask import Flask, request, jsonify

app = Flask(__name__)
MAGIC = 123456

if not mt5.initialize():
    raise RuntimeError("MT5 initialize() failed. Make sure MT5 is running and logged in.")
print("✅ Bridge server connected to MT5")

@app.route('/account_info')
def account_info():
    acc = mt5.account_info()
    if acc:
        return jsonify({'login': acc.login, 'balance': acc.balance, 'equity': acc.equity})
    return jsonify({'error': 'no account'}), 500

@app.route('/symbol_tick')
def symbol_tick():
    sym = request.args.get('symbol') or "XAUUSD"
    tick = mt5.symbol_info_tick(sym)
    if tick:
        return jsonify({'bid': tick.bid, 'ask': tick.ask})
    return jsonify({'error': f'Symbol {sym} not found'}), 404

@app.route('/place_limit_order', methods=['POST'])
def place_limit_order():
    data = request.get_json()
    symbol = data['symbol']
    order_type = data['order_type']
    price = float(data['price'])
    volume = float(data['volume'])
    comment = data.get('comment', 'Bridge')

    mt_type = mt5.ORDER_TYPE_BUY_LIMIT if order_type == 'buy_limit' else mt5.ORDER_TYPE_SELL_LIMIT
    req = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": symbol,
        "volume": volume,
        "type": mt_type,
        "price": price,
        "deviation": 5,
        "magic": MAGIC,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(req)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        return jsonify({'ticket': result.order, 'price': price, 'side': order_type})
    else:
        return jsonify({'error': result.comment, 'retcode': result.retcode}), 400

@app.route('/positions')
def positions():
    sym = request.args.get('symbol')
    pos = mt5.positions_get(symbol=sym, magic=MAGIC) if sym else mt5.positions_get(magic=MAGIC)
    out = []
    if pos:
        for p in pos:
            out.append({
                'ticket': p.ticket, 'symbol': p.symbol,
                'type': 'buy' if p.type == mt5.POSITION_TYPE_BUY else 'sell',
                'volume': p.volume, 'open_price': p.price_open
            })
    return jsonify(out)

@app.route('/open_orders')
def open_orders():
    sym = request.args.get('symbol')
    orders = mt5.orders_get(symbol=sym, magic=MAGIC) if sym else mt5.orders_get(magic=MAGIC)
    out = []
    if orders:
        for o in orders:
            out.append({
                'ticket': o.ticket, 'symbol': o.symbol,
                'type': 'buy_limit' if o.type == mt5.ORDER_TYPE_BUY_LIMIT else 'sell_limit',
                'volume': o.volume_initial, 'price': o.price_open
            })
    return jsonify(out)

@app.route('/close_positions', methods=['POST'])
def close_positions():
    data = request.get_json()
    symbol = data.get('symbol', 'XAUUSD')
    positions = mt5.positions_get(symbol=symbol, magic=MAGIC)
    closed = 0
    if positions:
        for pos in positions:
            order_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
            price = mt5.symbol_info_tick(symbol).bid if pos.type == mt5.POSITION_TYPE_BUY else mt5.symbol_info_tick(symbol).ask
            req = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": pos.volume,
                "type": order_type,
                "position": pos.ticket,
                "price": price,
                "deviation": 10,
                "magic": MAGIC,
                "comment": "GridBotClose",
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(req)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                closed += 1
    orders = mt5.orders_get(symbol=symbol, magic=MAGIC)
    cancelled = 0
    if orders:
        for o in orders:
            mt5.order_close(o.ticket)
            cancelled += 1
    return jsonify({'closed_positions': closed, 'cancelled_orders': cancelled})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
