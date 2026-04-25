#from datamodel import OrderDepth, TradingState, Order
from prosperity4bt.datamodel import OrderDepth, TradingState, Order

from typing import List, Dict, Any
import json
import math

# ─────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────

POSITION_LIMITS: Dict[str, int] = {
    "HYDROGEL_PACK": 200,
    "VELVETFRUIT_EXTRACT": 200,
    "VEV_4000": 300,
    "VEV_4500": 300,
    "VEV_5000": 300,
    "VEV_5100": 300,
    "VEV_5200": 300,
    "VEV_5300": 300,
    "VEV_5400": 300,
    "VEV_5500": 300,
    "VEV_6000": 300,
    "VEV_6500": 300,
}

# ─────────────────────────────────────────────
#  BASE STRATEGY
# ─────────────────────────────────────────────

class Strategy:
    def __init__(self, product: str, state: TradingState, memory: Dict[str, Any]):
        self.product  = product
        self.state    = state
        self.memory   = memory
        self.position = state.position.get(product, 0)
        self.limit    = POSITION_LIMITS.get(product, 20)
        self.od: OrderDepth = state.order_depths.get(product, OrderDepth())

    def best_bid(self):
        return max(self.od.buy_orders) if self.od.buy_orders else None

    def best_ask(self):
        return min(self.od.sell_orders) if self.od.sell_orders else None

    # Static Mid-Price for standard calculations
    def mid_price(self):
        bb, ba = self.best_bid(), self.best_ask()
        if bb is not None and ba is not None:
            return (bb + ba) / 2
        return None

    # Dynamic VWAP to capture true market gravity
    def vwap_price(self):
        total_value, total_vol = 0, 0
        for price, vol in self.od.buy_orders.items():
            total_value += price * vol
            total_vol += vol
        for price, vol in self.od.sell_orders.items():
            total_value += price * abs(vol)
            total_vol += abs(vol)
        
        if total_vol > 0:
            return total_value / total_vol
        return self.mid_price() 

    def buy_capacity(self):
        return self.limit - self.position

    def sell_capacity(self):
        return self.limit + self.position

    def clamp_buy(self, qty: int) -> int:
        return max(0, min(qty, self.buy_capacity()))

    def clamp_sell(self, qty: int) -> int:
        return max(0, min(qty, self.sell_capacity()))

    def run(self) -> List[Order]:
        raise NotImplementedError

# ─────────────────────────────────────────────
#  STRATEGY 1 — OPTIMIZED MARKET MAKING (For HYDROGEL_PACK)
# ─────────────────────────────────────────────
class MarketMakingStrategy(Strategy):
    def run(self) -> List[Order]:
        # 1. FAIR VALUE (Stable Mix)
        mid = self.mid_price() or 10000
        ema_key = f"ema_{self.product}"
        alpha = 0.19
        prev_ema = self.memory.get(ema_key, mid)
        ema = alpha * mid + (1 - alpha) * prev_ema
        self.memory[ema_key] = ema
        mult_mid = 0.631
        fv = mult_mid * mid + (1 - mult_mid) * ema 

        # 2. LINEAR SKEW
        skew = 0.08 * self.position
        base_fv = fv - skew

        # 3. PRICING LOGIC (Pennying)
        market_bid = self.best_bid()
        market_ask = self.best_ask()

        min_edge = 3.2
        max_bid = math.floor(base_fv - min_edge)
        min_ask = math.ceil(base_fv + min_edge)

        if market_bid is not None:
            bid_price = min(max_bid, market_bid + 1)
        else:
            bid_price = max_bid

        if market_ask is not None:
            ask_price = max(min_ask, market_ask - 1)
        else:
            ask_price = min_ask
        #26410

        # BASICS SIZE (STABLE)
        
        buy_size = 20
        sell_size = 20

        # Only slight reduction near limits to avoid blocking the bot,
        # but NO aggressive pushing.
        if self.position > 60:
            buy_size = 10  # Reduce buying to avoid hitting 200
            sell_size = 20 # Keep standard selling
        elif self.position < -60:
            buy_size = 20  # Keep standard buying
            sell_size = 10 # Reduce selling to avoid hitting -200

        buy_qty = self.clamp_buy(buy_size)
        sell_qty = self.clamp_sell(sell_size)

        orders: List[Order] = []

        # 4. VERY LIGHT TAKING ON BEST LEVEL ONLY
        if market_ask is not None and market_ask < math.floor(base_fv - 1) and buy_qty > 0:
            ask_vol = abs(self.od.sell_orders[market_ask])
            take_qty = min(buy_qty, ask_vol)
            if take_qty > 0:
                orders.append(Order(self.product, market_ask, take_qty))
                buy_qty = buy_qty - take_qty

        if market_bid is not None and market_bid > math.ceil(base_fv + 1) and sell_qty > 0:
            bid_vol = self.od.buy_orders[market_bid]
            take_qty = min(sell_qty, bid_vol)
            if take_qty > 0:
                orders.append(Order(self.product, market_bid, -take_qty))
                sell_qty = sell_qty - take_qty

        # 5. PASSIVE QUOTES WITH REMAINING SIZE
        if buy_qty > 0:
            orders.append(Order(self.product, bid_price, buy_qty))
        if sell_qty > 0:
            orders.append(Order(self.product, ask_price, -sell_qty))

        return orders

# ─────────────────────────────────────────────
#  STRATEGY 2 — NULL STRATEGY (Do Nothing)
# ─────────────────────────────────────────────
class NullStrategy(Strategy):
    """Strategia neutra che non esegue ordini."""
    def run(self) -> List[Order]:
        return []

# ─────────────────────────────────────────────
#  PRODUCT → STRATEGY ROUTING
# ─────────────────────────────────────────────

def get_strategy(product: str, state: TradingState, memory: Dict) -> Strategy:
    # Mappatura: Commodities a MarketMaking, Derivati a NullStrategy
    if product in ["HYDROGEL_PACK"]:
        return MarketMakingStrategy(product, state, memory)
    
    # Per tutti i derivati VEV_XXXX
    return NullStrategy(product, state, memory)

# ─────────────────────────────────────────────
#  TRADER ENTRY POINT
# ─────────────────────────────────────────────

class Trader:
    def run(self, state: TradingState):
        try:
            memory: Dict[str, Any] = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            memory = {}

        result: Dict[str, List[Order]] = {}

        for product in state.order_depths:
            strategy = get_strategy(product, state, memory)
            try:
                orders = strategy.run()
            except Exception as e:
                print(f"[ERROR] {product}: {e}")
                orders = []
            result[product] = orders

        traderData = json.dumps(memory)
        return result, 0, traderData