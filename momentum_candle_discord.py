"""
Momentum Candle V3 - Python + MetaTrader5 + Discord Notifier
Konversi dari Pine Script "Momentum Candle V3 by Sekolah Trading"

Requirements:
    pip install MetaTrader5 requests

Catatan penting:
- Script ini HARUS dijalankan di Windows dengan terminal MetaTrader5 (MT5)
  sudah terinstall dan sudah login ke akun broker (bisa demo/real).
- Pastikan symbol XAUUSD dan USDJPY sudah muncul di Market Watch pada
  terminal MT5. Jika broker Anda memakai suffix (mis. "XAUUSD.a",
  "USDJPY.m"), ubah nama di SYMBOL_CONFIG di bawah agar sesuai persis.
"""

import time
import requests
import MetaTrader5 as mt5
from datetime import datetime

# ============================================================
# KONFIGURASI
# ============================================================

DISCORD_WEBHOOK_URL = "https://discordapp.com/api/webhooks/1523675229627617371/av1Us5m_cEz-s9wwL8edAZnZhk-2IC6ZuJ3lBehOuak4bc8b_Pygpp11jTZFoFzAhMfc"

# Path lengkap ke terminal64.exe. WAJIB diisi kalau dijalankan lewat Wine,
# karena auto-detect MT5 sering gagal di Wine (error -10003 IPC initialize
# failed). Contoh isi path (pakai format Windows, bukan path Linux):
#   r"C:\Program Files\MetaTrader 5\terminal64.exe"
# Cari lokasi file ini dengan: find ~/.wine -iname "terminal64.exe"
MT5_TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"

# Timeframe yang dipantau (tambahkan "M15" ke list ini jika perlu nanti)
ACTIVE_TIMEFRAMES = ["M5"]

# Jeda antar pengecekan (detik). Jangan terlalu besar karena window
# alert Pine Script cuma 20-90 detik sebelum bar close.
POLL_INTERVAL = 3

# Konfigurasi tiap pair: pip size + minimum body (pip) untuk tiap TF.
# "input_pip" = 0 artinya pakai "default_pip" (persis logika Pine Script asli).
SYMBOL_CONFIG = {
    "XAUUSD.vxc": {
        "pip_size": 0.1,
        "M5":  {"input_pip": 40, "default_pip": 35},
        "M15": {"input_pip": 50, "default_pip": 45},
    },
}

TF_MAP = {
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
}

TF_SECONDS = {
    "M5": 300,
    "M15": 900,
}

# Menyimpan bar terakhir yang sudah dikirim notifikasinya, supaya tidak
# terkirim berulang kali selama window alert (20-90 detik) masih aktif.
# key: (symbol, tf, direction) -> bar_open_time
last_alert_sent = {}


# ============================================================
# FUNGSI DISCORD
# ============================================================

def send_discord_alert(symbol, tf, direction, price):
    if not DISCORD_WEBHOOK_URL or "PASTE_WEBHOOK" in DISCORD_WEBHOOK_URL:
        print("[WARNING] Discord webhook belum diset, notifikasi dilewati.")
        return

    color = 3447003 if direction == "BULLISH" else 15158332  # biru / merah
    emoji = "🔼" if direction == "BULLISH" else "🔽"

    payload = {
        "content": "@everyone",
        "allowed_mentions": {"parse": ["everyone"]},
        "embeds": [
            {
                "title": f"{emoji} Momentum Candle {direction}",
                "description": f"**{symbol}** ({tf}) — Momentum candle valid.",
                "color": color,
                "fields": [
                    {"name": "Harga", "value": str(round(price, 5)), "inline": True},
                    {"name": "Waktu", "value": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "inline": True},
                ],
                "footer": {"text": "Momentum Candle V3 by Sekolah Trading"},
            }
        ]
    }

    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code not in (200, 204):
            print(f"[ERROR] Gagal kirim Discord: {resp.status_code} {resp.text}")
        else:
            print(f"[OK] Notifikasi terkirim: {symbol} {tf} {direction}")
    except Exception as e:
        print(f"[ERROR] Exception saat kirim Discord: {e}")


# ============================================================
# LOGIKA MOMENTUM CANDLE (replikasi 1:1 dari Pine Script)
# ============================================================

def get_min_range(symbol, tf):
    cfg = SYMBOL_CONFIG[symbol]
    pip_size = cfg["pip_size"]
    tf_cfg = cfg[tf]
    use_pip = tf_cfg["input_pip"] if tf_cfg["input_pip"] > 0 else tf_cfg["default_pip"]
    return use_pip * pip_size


def analyze_symbol(symbol, tf):
    """
    Menghitung sinyal untuk 1 symbol + 1 timeframe berdasarkan bar yang
    sedang berjalan (belum close), sama seperti barstate.isconfirmed
    = false di Pine Script.
    Return None jika data tidak cukup.
    """
    mt5_tf = TF_MAP[tf]

    # index -1 = bar yang sedang berjalan (current, belum close)
    # index -2 = bar sebelumnya -> dipakai untuk close[1]
    rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, 2)
    if rates is None or len(rates) < 2:
        return None

    current_bar = rates[-1]
    prev_bar = rates[-2]

    open_ = float(current_bar["open"])
    high = float(current_bar["high"])
    low = float(current_bar["low"])
    close = float(current_bar["close"])
    prev_close = float(prev_bar["close"])
    bar_open_time = int(current_bar["time"])

    min_range = get_min_range(symbol, tf)

    total_range = abs(close - open_)
    upper_wick = high - max(open_, close)
    lower_wick = min(open_, close) - low
    total_wick = upper_wick + lower_wick

    is_big_candle = total_range >= min_range
    denom = total_range + total_wick
    is_wick_short = (total_wick / denom) <= 0.3 if denom > 0 else False
    is_bullish = close > open_
    is_bearish = (close < open_) or (close > open_ and close < prev_close)

    show_signal = is_big_candle and is_wick_short and (is_bullish or is_bearish)

    # Waktu tersisa sebelum bar close, pakai waktu server MT5 (dari tick)
    # supaya sinkron dengan bar_open_time (juga dari MT5).
    tick = mt5.symbol_info_tick(symbol)
    server_now = tick.time if tick else time.time()
    bar_close_time = bar_open_time + TF_SECONDS[tf]
    bar_time_left_ms = (bar_close_time - server_now) * 1000

    alert_window = 20000 <= bar_time_left_ms <= 90000

    bull_signal = show_signal and is_bullish and alert_window
    bear_signal = show_signal and is_bearish and alert_window

    return {
        "symbol": symbol,
        "tf": tf,
        "bar_open_time": bar_open_time,
        "close": close,
        "bull_signal": bull_signal,
        "bear_signal": bear_signal,
        "bar_time_left_ms": bar_time_left_ms,
    }


def check_and_alert(symbol, tf):
    result = analyze_symbol(symbol, tf)
    if result is None:
        return

    for direction, is_triggered in (
        ("BULLISH", result["bull_signal"]),
        ("BEARISH", result["bear_signal"]),
    ):
        if not is_triggered:
            continue

        key = (symbol, tf, direction)
        bar_time = result["bar_open_time"]

        # Hindari kirim ulang untuk bar yang sama selama window 20-90s masih aktif
        if last_alert_sent.get(key) == bar_time:
            continue

        send_discord_alert(symbol, tf, direction, result["close"])
        last_alert_sent[key] = bar_time


# ============================================================
# MAIN LOOP
# ============================================================

def main():
    if not mt5.initialize(path=MT5_TERMINAL_PATH):
        print(f"[ERROR] Gagal koneksi ke MT5: {mt5.last_error()}")
        print(f"[HINT] Cek apakah path berikut benar dan file-nya ada: {MT5_TERMINAL_PATH}")
        print("[HINT] Cari path yang benar dengan: find ~/.wine -iname \"terminal64.exe\"")
        return

    print("[OK] Terkoneksi ke MT5. Memulai monitoring...")
    print(f"Symbol: {list(SYMBOL_CONFIG.keys())} | Timeframe: {ACTIVE_TIMEFRAMES}")

    # Pastikan symbol muncul di Market Watch
    for symbol in SYMBOL_CONFIG:
        if not mt5.symbol_select(symbol, True):
            print(f"[WARNING] Symbol {symbol} tidak ditemukan / gagal diaktifkan di Market Watch.")

    try:
        while True:
            for symbol in SYMBOL_CONFIG:
                for tf in ACTIVE_TIMEFRAMES:
                    try:
                        check_and_alert(symbol, tf)
                    except Exception as e:
                        print(f"[ERROR] {symbol} {tf}: {e}")
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("Dihentikan oleh user.")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
