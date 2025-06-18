import time
import datetime
import requests
import pandas as pd
import numpy as np
from binance import Client

# === CONFIGURATION ===
API_KEY    = "au1NgG30pwsUC8HGOaoIGyP81nBC6tdFiIVtM0E9rkrxbW73GdkBDeQP7ES3a1GC"
API_SECRET = "mv2Wf4xEPICO36KET5bxYKR6oyX6Exj3bCPf8x8YVPSrniOiVLcDgWtHcjovJbG6"
client     = Client(API_KEY, API_SECRET)

PAIRS = [
  "DOGEUSDT", "BNBUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT",
  "ADAUSDT", "XRPUSDT", "DOTUSDT", "AVAXUSDT", "SHIBUSDT",
  "XLMUSDT", "XMRUSDT", "IMXUSDT",
  "CRVUSDT", "NEARUSDT", "BCHUSDT", "MKRUSDT", "FILUSDT",
  "LTCUSDT", "SNXUSDT", "AAVEUSDT", "RUNEUSDT", "ICPUSDT"
]


# === INTERVALLE MODIFIABLE ===
INTERVAL        = Client.KLINE_INTERVAL_1HOUR  # Exemples : _1MINUTE, _5MINUTE, _15MINUTE, _1HOUR
INTERVAL_STRING = "1h"  # Correspondance texte pour la synchronisation (ex: '1m', '5m', '15m', '1h')

TELE_TOKEN      = "7602849001:AAFCXsN5glTWnPVnnwaeyLS3oO0tBO3Z4is"
CHAT_ID         = "-4917340526"

# === STRATEGY PARAMETERS ===
only_long        = True
only_short       = False
fast_length      = 21
slow_length      = 50
use_rsi          = True
rsi_len          = 14
rsi_entry_long   = 55
rsi_entry_short  = 45
use_adx          = True
adx_len          = 14
adx_smooth       = 14
adx_min          = 20
atr_period       = 14
swing_lookback   = 5
risk_multiplier  = 1
tp_multiplier    = 2
use_trailing     = True
trailing_percent = 5.0

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print("🚨 Erreur Telegram:", e)

def get_klines(symbol):
    data = client.get_klines(symbol=symbol, interval=INTERVAL, limit=500)
    df = pd.DataFrame(data, columns=[
        "timestamp","open","high","low","close","volume",
        "close_time","qav","trades","taker_base","taker_quote","ignore"
    ])
    df = df.astype({
        "open": float, "high": float, "low": float, "close": float
    })

    # TR + ATR
    df["tr"] = np.maximum.reduce([
        df["high"] - df["low"],
        abs(df["high"] - df["close"].shift()),
        abs(df["low"] - df["close"].shift())
    ])
    df["atr"] = df["tr"].ewm(alpha=1/atr_period, adjust=False).mean()

    # EMAs
    df["ema_fast"] = df["close"].ewm(span=fast_length).mean()
    df["ema_slow"] = df["close"].ewm(span=slow_length).mean()

    # RSI
    delta = df["close"].diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_g = gain.rolling(rsi_len).mean()
    avg_l = loss.rolling(rsi_len).mean()
    df["rsi"] = 100 - (100 / (1 + avg_g / avg_l))

    # ADX
    up = df["high"] - df["high"].shift()
    dn = df["low"].shift() - df["low"]
    df["+dm"] = np.where((up > dn) & (up > 0), up, 0.0)
    df["-dm"] = np.where((dn > up) & (dn > 0), dn, 0.0)
    df["+di"] = 100 * df["+dm"].rolling(adx_smooth).mean() / df["atr"]
    df["-di"] = 100 * df["-dm"].rolling(adx_smooth).mean() / df["atr"]
    dx = abs(df["+di"] - df["-di"]) / (df["+di"] + df["-di"]) * 100
    df["adx"] = dx.rolling(adx_len).mean()

    return df

def analyze(df, symbol):
    last = df.iloc[-1]
    prev = df.iloc[-2]
    adx_ok   = (not use_adx) or (last["adx"] > adx_min)
    rsi_ok_l = (not use_rsi) or (last["rsi"] > rsi_entry_long)
    rsi_ok_s = (not use_rsi) or (last["rsi"] < rsi_entry_short)

    bull_cross = prev["ema_fast"] < prev["ema_slow"] and last["ema_fast"] > last["ema_slow"] and rsi_ok_l and adx_ok
    bear_cross = prev["ema_fast"] > prev["ema_slow"] and last["ema_fast"] < last["ema_slow"] and rsi_ok_s and adx_ok

    pivot_low  = df["low"].rolling(swing_lookback).min().iloc[-2]
    pivot_high = df["high"].rolling(swing_lookback).max().iloc[-2]

    if bull_cross and only_long:
        sl    = pivot_low - risk_multiplier * last["atr"]
        risk  = last["close"] - sl
        tp    = last["close"] + tp_multiplier * risk
        trail = trailing_percent/100 * last["close"] if use_trailing else None
        return "LONG", last["close"], sl, tp, trail

    if bear_cross and only_short:
        sl    = pivot_high + risk_multiplier * last["atr"]
        risk  = sl - last["close"]
        tp    = last["close"] - tp_multiplier * risk
        trail = trailing_percent/100 * last["close"] if use_trailing else None
        return "SHORT", last["close"], sl, tp, trail

    return None, None, None, None, None

def wait_until_next_candle(interval: str):
    now = datetime.datetime.now()
    unit = interval[-1]
    value = int(interval[:-1])

    if unit == 'm':
        minutes = value
        next_time = now.replace(second=0, microsecond=0)
        next_time += datetime.timedelta(minutes=minutes - (now.minute % minutes))
    elif unit == 'h':
        hours = value
        next_time = now.replace(minute=0, second=0, microsecond=0)
        next_time += datetime.timedelta(hours=hours - (now.hour % hours))
    else:
        print("⛔ Intervalle non supporté pour l'attente.")
        return

    wait = (next_time - now).total_seconds()
    print(f"⏳ Attente jusqu'à {next_time.strftime('%H:%M:%S')} ({int(wait)}s)...")
    time.sleep(wait)

# === MAIN LOOP ===
print(f"🚀 Bot lancé (intervalle : {INTERVAL_STRING})")

while True:
    def lambda_handler(event, context):
        for pair in PAIRS:
            try:
                print(f"🔍 {pair}")
                df = get_klines(pair)
                sig, price, sl, tp, trail = analyze(df, pair)
                if sig:
                    msg = f"✅ {sig} {pair}\nPrix: {price:.3f}\nSL: {sl:.3f}\nTP: {tp:.3f}"
                    if trail:
                        msg += f"\nTrailing: {trail:.3f}"
                    send_telegram(msg)
                    print(msg)
                else:
                    print(f"❌ Aucun signal {pair}")
            except Exception as e:
                print(f"🚨 Erreur {pair} :", e)
        wait_until_next_candle(INTERVAL_STRING)
