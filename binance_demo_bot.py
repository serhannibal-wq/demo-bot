#!/usr/bin/env python3
"""
Binance DEMO (paper trading) botu - sanal 1000 USDT ile. AGRESİF MOD.
GERÇEK EMİR GÖNDERMEZ. API anahtarı gerektirmez; sadece Binance'in
herkese açık fiyat verisini (klines) okur.

Kullanım:
  python binance_demo_bot.py backtest --days 365     # geçmiş veride test
  python binance_demo_bot.py paper                   # canlı demo (4 saatlik mumlar)
  python binance_demo_bot.py status                  # demo hesabın durumu

Sadece Python 3.9+ standart kütüphanesi kullanır (ek kurulum yok).
"""
import argparse, csv, json, math, os, sys, time, urllib.request, urllib.parse
from datetime import datetime, timezone

# ------------------------------------------------------------------ AYARLAR
CONFIG = {
    "start_balance": 1000.0,          # sanal USDT
    "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
                "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "ADAUSDT"],
    "interval": "15m",                # agresif mod: 15 dakikalık mumlar
    "fee": 0.001,                     # Binance spot %0.1 (her işlem)
    "slippage": 0.0005,               # %0.05 kayma varsayımı
    "risk_per_trade": 0.03,           # agresif: işlem başı sermayenin %3'ü riske edilir
    "max_position_pct": 0.50,         # tek coine en fazla sermayenin %50'si
    "max_open_positions": 4,
    "atr_stop_mult": 2.0,             # ilk stop = giriş - 2*ATR
    "atr_trail_mult": 2.5,            # trend işlemlerinde iz süren stop
    "breakout_len": 20,               # Donchian kırılım periyodu
    "rsi_oversold": 33,
    "bounce_target_atr": 2.0,
    "bounce_max_bars": 16,            # tepki alımında en fazla 16 mum (4 saat) tut
    "bounce_risk_mult": 0.75,
    "dd_brake": 0.15,                 # zirveden %15 düşüşte risk yarıya iner
    "dd_halt": 0.30,                  # zirveden %30 düşüşte 3 gün yeni işlem açılmaz
    "state_file": "demo_state.json",
    "trades_file": "demo_trades.csv",
}
HOSTS = ["https://api.binance.com", "https://data-api.binance.vision"]
INTERVAL_MS = {"15m": 900_000, "1h": 3600_000, "4h": 4 * 3600_000, "1d": 86400_000}

# ------------------------------------------------------------------ VERİ
def http_json(path, params):
    last = None
    for h in HOSTS:
        url = f"{h}{path}?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "demo-bot/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except Exception as e:  # sıradaki sunucuyu dene
            last = e
    raise RuntimeError(f"Binance'e ulaşılamadı: {last}")

def fetch_klines(symbol, interval, start_ms=None, limit=1000):
    """Kapanmış mumları döndürür: [ts, open, high, low, close, volume]"""
    out, now = [], int(time.time() * 1000)
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    while True:
        if start_ms: params["startTime"] = start_ms
        rows = http_json("/api/v3/klines", params)
        if not rows: break
        for k in rows:
            if k[6] < now:  # sadece kapanmış mum
                out.append([k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])])
        if len(rows) < limit or start_ms is None: break
        start_ms = rows[-1][0] + 1
        time.sleep(0.2)
    return out

# ------------------------------------------------------------------ İNDİKATÖRLER
def ema(vals, n):
    k, out, e = 2 / (n + 1), [], None
    for v in vals:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out

def rsi(closes, n=14):
    out, g, l = [None] * len(closes), 0.0, 0.0
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        up, dn = max(d, 0), max(-d, 0)
        if i <= n:
            g += up / n; l += dn / n
            if i == n: out[i] = 100 - 100 / (1 + g / l) if l else 100
        else:
            g = (g * (n - 1) + up) / n; l = (l * (n - 1) + dn) / n
            out[i] = 100 - 100 / (1 + g / l) if l else 100
    return out

def atr(bars, n=14):
    out, a = [None] * len(bars), None
    for i in range(1, len(bars)):
        h, lo, pc = bars[i][2], bars[i][3], bars[i - 1][4]
        tr = max(h - lo, abs(h - pc), abs(lo - pc))
        a = tr if a is None else (a * (n - 1) + tr) / n
        if i >= n: out[i] = a
    return out

def indicators(bars):
    c = [b[4] for b in bars]
    return {"ema50": ema(c, 50), "ema200": ema(c, 200), "rsi": rsi(c), "atr": atr(bars)}

# ------------------------------------------------------------------ HESAP / MOTOR
class Account:
    def __init__(self, cfg, state=None):
        self.cfg = cfg
        s = state or {}
        self.cash = s.get("cash", cfg["start_balance"])
        self.positions = s.get("positions", {})   # sym -> dict
        self.peak = s.get("peak", cfg["start_balance"])
        self.trades = []
        self.last_ts = s.get("last_ts", {})
        self.started = s.get("started")

    def equity(self, prices):
        return self.cash + sum(p["qty"] * prices.get(s, p["entry"]) for s, p in self.positions.items())

    def _log(self, ts, sym, side, price, qty, reason, pnl=None):
        t = {"time": datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M"),
             "symbol": sym, "side": side, "price": round(price, 6), "qty": round(qty, 6),
             "value_usdt": round(price * qty, 2), "reason": reason,
             "pnl_usdt": None if pnl is None else round(pnl, 2), "cash_after": round(self.cash, 2)}
        self.trades.append(t)
        return t

    def buy(self, ts, sym, price, stop, kind, prices):
        cfg = self.cfg
        eq = self.equity(prices)
        dd = 1 - eq / self.peak
        if dd >= cfg["dd_halt"]:
            # 7 gün (42 x 4s mum) bekle, sonra yeni zirve referansıyla devam et
            self.halt_since = getattr(self, "halt_since", None) or ts
            if ts - self.halt_since < 3 * 86400_000: return None
            self.peak, self.halt_since, dd = eq, None, 0
        risk = cfg["risk_per_trade"] * (0.5 if dd >= cfg["dd_brake"] else 1.0)
        if kind == "bounce": risk *= cfg["bounce_risk_mult"]
        fill = price * (1 + cfg["slippage"])
        per_unit = fill - stop
        if per_unit <= 0: return None
        qty = eq * risk / per_unit
        qty = min(qty, eq * cfg["max_position_pct"] / fill, self.cash / (fill * (1 + cfg["fee"])))
        if qty * fill < 10: return None             # Binance min. emir ~10 USDT
        self.cash -= qty * fill * (1 + cfg["fee"])
        self.positions[sym] = {"qty": qty, "entry": fill, "stop": stop, "kind": kind,
                               "high": fill, "bars": 0, "ts": ts}
        return self._log(ts, sym, "BUY", fill, qty, kind)

    def sell(self, ts, sym, price, reason):
        cfg, p = self.cfg, self.positions.pop(sym)
        fill = price * (1 - cfg["slippage"])
        proceeds = p["qty"] * fill * (1 - cfg["fee"])
        cost = p["qty"] * p["entry"] * (1 + cfg["fee"])
        self.cash += proceeds
        return self._log(ts, sym, "SELL", fill, p["qty"], reason, proceeds - cost)

def step(acc, sym, bars, ind, i, prices):
    """Tek bir kapanmış mumda strateji kararı. bars[i] = son kapanmış mum."""
    cfg = acc.cfg
    ts, o, h, l, c, _ = bars[i]
    a, r, e50, e200 = ind["atr"][i], ind["rsi"][i], ind["ema50"][i], ind["ema200"][i]
    if a is None or r is None or i < 200: return
    # --- açık pozisyon yönetimi
    if sym in acc.positions:
        p = acc.positions[sym]
        p["bars"] += 1
        if l <= p["stop"]:                                   # stop tetiklendi
            acc.sell(ts, sym, min(p["stop"], o), "stop"); return
        if p["kind"] == "trend":
            p["high"] = max(p["high"], c)
            p["stop"] = max(p["stop"], p["high"] - cfg["atr_trail_mult"] * a)
            if c < e50 and c < p["entry"] * 0.995:
                acc.sell(ts, sym, c, "trend bozuldu")
        else:  # bounce
            target = p["entry"] + cfg["bounce_target_atr"] * p.get("atr", a)
            if h >= target: acc.sell(ts, sym, max(target, o), "hedef")
            elif p["bars"] >= cfg["bounce_max_bars"]: acc.sell(ts, sym, c, "süre doldu")
        return
    if len(acc.positions) >= cfg["max_open_positions"]: return
    # --- yeni giriş sinyalleri
    n = cfg["breakout_len"]
    prev_high = max(b[2] for b in bars[i - n:i])
    # agresif: uzun vadeli trend şartı yok; kısa vadeli momentum yeterli
    if c > prev_high and c > e50 and r < 80:
        acc.buy(ts, sym, c, c - cfg["atr_stop_mult"] * a, "trend", prices)
    elif r < cfg["rsi_oversold"] and c > o and c > l + 0.4 * (h - l):
        t = acc.buy(ts, sym, c, c - 1.5 * a, "bounce", prices)
        if t: acc.positions[sym]["atr"] = a

# ------------------------------------------------------------------ RAPOR
def report(acc, curve, start_eq, bh=None):
    eq = curve[-1][1]
    peak, mdd = curve[0][1], 0
    for _, v in curve:
        peak = max(peak, v); mdd = max(mdd, 1 - v / peak)
    sells = [t for t in acc.trades if t["side"] == "SELL"]
    wins = [t for t in sells if t["pnl_usdt"] > 0]
    months = {}
    for ts, v in curve:
        months[datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y-%m")] = v
    print("\n================ SONUÇ ================")
    print(f"Başlangıç: {start_eq:.2f} USDT  ->  Bitiş: {eq:.2f} USDT  ({(eq/start_eq-1)*100:+.2f}%)")
    print(f"Maks. düşüş (drawdown): %{mdd*100:.1f}")
    print(f"Kapanan işlem: {len(sells)}  |  Kazanma oranı: %{(len(wins)/len(sells)*100 if sells else 0):.0f}")
    if bh is not None: print(f"Karşılaştırma - eşit ağırlıklı al-tut: {bh*100:+.2f}%")
    print("\nAylık getiri:")
    prev, hit = start_eq, 0
    for m, v in months.items():
        ch = v / prev - 1; prev = v; hit += ch >= 0.15
        print(f"  {m}: {ch*100:+6.2f}%  {'✅ hedef' if ch >= 0.15 else ''}")
    print(f"\n%15 hedefini tutturan ay: {hit}/{len(months)}")

def save_trades(trades, path):
    if not trades: return
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(trades[0].keys()))
        if new: w.writeheader()
        w.writerows(trades)

# ------------------------------------------------------------------ MODLAR
def run_backtest(days, data=None):
    cfg = CONFIG
    step_ms = INTERVAL_MS[cfg["interval"]]
    warm = 210 * step_ms
    start = int(time.time() * 1000) - days * 86400_000 - warm
    if data is None:
        data = {}
        for s in cfg["symbols"]:
            print(f"Veri indiriliyor: {s} ...")
            data[s] = fetch_klines(s, cfg["interval"], start)
    inds = {s: indicators(b) for s, b in data.items()}
    idx = {s: {b[0]: i for i, b in enumerate(b_)} for s, b_ in data.items()}
    all_ts = sorted(set(ts for b in data.values() for ts in (x[0] for x in b)))
    acc, curve, prices = Account(cfg), [], {}
    test_start = all_ts[0] + warm
    first_px = {}
    for ts in all_ts:
        for s in cfg["symbols"]:
            i = idx[s].get(ts)
            if i is None: continue
            prices[s] = data[s][i][4]
            if ts >= test_start:
                first_px.setdefault(s, prices[s])
                step(acc, s, data[s], inds[s], i, prices)
        if ts >= test_start:
            e = acc.equity(prices); acc.peak = max(acc.peak, e); curve.append((ts, e))
    bh = sum(prices[s] / first_px[s] for s in first_px) / len(first_px) - 1
    report(acc, curve, cfg["start_balance"], bh)
    if os.path.exists("backtest_trades.csv"): os.remove("backtest_trades.csv")
    save_trades(acc.trades, "backtest_trades.csv")
    print("İşlem listesi: backtest_trades.csv")
    return acc, curve

def load_state():
    p = CONFIG["state_file"]
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None

def save_state(acc, prices=None):
    json.dump({"cash": acc.cash, "positions": acc.positions, "peak": acc.peak,
               "last_ts": acc.last_ts, "prices": prices or {},
               "start_balance": CONFIG["start_balance"],
               "started": getattr(acc, "started", None) or datetime.now(timezone.utc).isoformat(),
               "updated": datetime.now(timezone.utc).isoformat()},
              open(CONFIG["state_file"], "w", encoding="utf-8"), indent=2)

def paper_tick(acc):
    cfg, prices, cache = CONFIG, {}, {}
    for s in cfg["symbols"]:
        bars = fetch_klines(s, cfg["interval"], None, 300)
        cache[s] = bars; prices[s] = bars[-1][4]
    for s, bars in cache.items():
        ind, i = indicators(bars), len(bars) - 1
        if acc.last_ts.get(s) == bars[i][0]: continue      # bu mum zaten işlendi
        acc.last_ts[s] = bars[i][0]
        before = len(acc.trades)
        step(acc, s, bars, ind, i, prices)
        for t in acc.trades[before:]:
            print(f"  >> {t['time']} {t['side']} {t['symbol']} @ {t['price']} ({t['reason']})"
                  + (f" PnL {t['pnl_usdt']:+.2f}" if t["pnl_usdt"] is not None else ""))
    eq = acc.equity(prices); acc.peak = max(acc.peak, eq)
    save_trades(acc.trades, cfg["trades_file"]); acc.trades = []
    save_state(acc, prices)
    hist_p = "equity_history.json"
    hist = json.load(open(hist_p, encoding="utf-8")) if os.path.exists(hist_p) else []
    hist.append({"t": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "equity": round(eq, 2)})
    json.dump(hist[-20000:], open(hist_p, "w", encoding="utf-8"))
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{now}] Sermaye: {eq:.2f} USDT ({(eq/cfg['start_balance']-1)*100:+.2f}%) | "
          f"Nakit: {acc.cash:.2f} | Açık: {', '.join(acc.positions) or '-'}")

def run_paper(once=False):
    acc = Account(CONFIG, load_state())
    print("DEMO mod - gerçek emir gönderilmez. Durdurmak için Ctrl+C.")
    while True:
        try: paper_tick(acc)
        except Exception as e: print("Hata (tekrar denenecek):", e)
        if once: break
        time.sleep(5 * 60)    # 5 dakikada bir kontrol; yeni mum kapanınca işlem yapar

def show_status():
    st = load_state()
    if not st: print("Henüz demo hesap yok. Önce: python binance_demo_bot.py paper"); return
    prices = {s: fetch_klines(s, "1m", None, 2)[-1][4] for s in st["positions"]}
    acc = Account(CONFIG, st)
    eq = acc.equity(prices)
    print(f"Sermaye: {eq:.2f} USDT ({(eq/CONFIG['start_balance']-1)*100:+.2f}%)  Nakit: {acc.cash:.2f}")
    for s, p in st["positions"].items():
        print(f"  {s}: {p['qty']:.5f} @ {p['entry']:.4f}  şimdi {prices[s]:.4f}  "
              f"({(prices[s]/p['entry']-1)*100:+.2f}%)  stop {p['stop']:.4f}  [{p['kind']}]")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Binance demo trading botu (sanal 1000 USDT)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backtest"); b.add_argument("--days", type=int, default=365)
    p = sub.add_parser("paper"); p.add_argument("--once", action="store_true")
    sub.add_parser("status")
    a = ap.parse_args()
    if a.cmd == "backtest": run_backtest(a.days)
    elif a.cmd == "paper": run_paper(a.once)
    else: show_status()
