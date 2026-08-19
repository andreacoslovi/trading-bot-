"""
BOT DI TRADING - PAPER TRADING SU ALPACA
==========================================

Cosa fa questo script:
- Si collega ad Alpaca in modalità PAPER TRADING (soldi finti, zero rischio)
- Usa una strategia semplicissima: incrocio di due medie mobili (SMA)
    - Se la media veloce (breve periodo) supera quella lenta -> compra
    - Se la media veloce scende sotto quella lenta -> vende
- Logga tutto quello che fa, così puoi capire cosa succede

IMPORTANTE:
- Questo è SOLO per imparare e testare. Gira in paper trading, non usa soldi veri.
- Prima di anche solo pensare a soldi veri, fai girare questo per settimane
  e guarda i risultati con occhio critico.
- Le strategie a media mobile semplice sono didattiche: nella pratica
  raramente sono profittevoli da sole su azioni USA senza ulteriori filtri
  (costi di transazione, slippage, falsi segnali in mercati laterali, ecc).

COME INIZIARE:
1. Crea un account gratuito su https://alpaca.markets
2. Prendi le tue API KEY e SECRET dalla dashboard "Paper Trading"
3. Installa le librerie necessarie:
     pip install alpaca-py pandas
4. Inserisci le tue chiavi qui sotto (o meglio, come variabili d'ambiente)
5. Esegui: python trading_bot_alpaca.py
"""

import os
import time
import logging
from datetime import datetime, timedelta

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# ==========================================
# CONFIGURAZIONE
# ==========================================

# Meglio mettere le chiavi come variabili d'ambiente invece che scriverle qui:
#   export ALPACA_API_KEY="la_tua_chiave"
#   export ALPACA_SECRET_KEY="la_tua_chiave_segreta"
API_KEY = os.getenv("ALPACA_API_KEY", "INSERISCI_QUI_LA_TUA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "INSERISCI_QUI_LA_TUA_SECRET_KEY")

SYMBOL = "AAPL"          # Titolo su cui operare
QTY = 1                  # Quante azioni comprare/vendere per volta
SMA_FAST = 10            # Media mobile veloce (periodi)
SMA_SLOW = 30            # Media mobile lenta (periodi)
CHECK_INTERVAL_SEC = 60 * 15   # Ogni quanto controllare (15 minuti)

# Circuit breaker: se le perdite superano questa soglia, il bot si ferma da solo
MAX_DAILY_LOSS_PCT = 2.0   # Stop se perdi più del 2% del capitale in un giorno

# ==========================================
# LOGGING - per tenere traccia di tutto quello che fa il bot
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("trading_bot.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


# ==========================================
# CLIENT ALPACA (paper=True = SOLDI FINTI)
# ==========================================
trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)


def get_account_info():
    """Recupera le info sull'account (saldo, potere d'acquisto, ecc)."""
    account = trading_client.get_account()
    return account


def get_recent_closes(symbol: str, n_bars: int = 40):
    """Scarica le ultime n_bars candele giornaliere per calcolare le medie mobili."""
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=datetime.now() - timedelta(days=n_bars * 2),  # margine per weekend/festivi
    )
    bars = data_client.get_stock_bars(request).df
    closes = bars["close"].tail(n_bars).tolist()
    return closes


def calculate_sma(prices: list, period: int):
    """Calcola la media mobile semplice sugli ultimi 'period' prezzi."""
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


def get_current_position(symbol: str):
    """Controlla se abbiamo già una posizione aperta su questo titolo."""
    try:
        position = trading_client.get_open_position(symbol)
        return float(position.qty)
    except Exception:
        return 0.0


def place_order(symbol: str, qty: int, side: OrderSide):
    """Piazza un ordine di mercato (compra o vendi)."""
    order_request = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=side,
        time_in_force=TimeInForce.DAY
    )
    order = trading_client.submit_order(order_request)
    log.info(f"ORDINE INVIATO: {side.value.upper()} {qty} {symbol} - ID: {order.id}")
    return order


def check_circuit_breaker(account):
    """Se abbiamo perso troppo oggi, blocchiamo il bot per sicurezza."""
    equity = float(account.equity)
    last_equity = float(account.last_equity)
    if last_equity == 0:
        return False
    daily_change_pct = ((equity - last_equity) / last_equity) * 100
    if daily_change_pct <= -MAX_DAILY_LOSS_PCT:
        log.warning(
            f"CIRCUIT BREAKER ATTIVATO: perdita giornaliera {daily_change_pct:.2f}% "
            f"supera il limite di -{MAX_DAILY_LOSS_PCT}%. Bot fermato."
        )
        return True
    return False


def run_strategy():
    """Un ciclo della strategia: controlla i prezzi e decide se comprare/vendere."""
    account = get_account_info()

    if check_circuit_breaker(account):
        return "STOP"

    closes = get_recent_closes(SYMBOL, n_bars=SMA_SLOW + 5)
    if len(closes) < SMA_SLOW:
        log.info("Dati insufficienti per calcolare le medie mobili, aspetto.")
        return "CONTINUE"

    sma_fast = calculate_sma(closes, SMA_FAST)
    sma_slow = calculate_sma(closes, SMA_SLOW)
    current_position = get_current_position(SYMBOL)

    log.info(
        f"{SYMBOL} | SMA{SMA_FAST}={sma_fast:.2f} | SMA{SMA_SLOW}={sma_slow:.2f} | "
        f"Posizione attuale: {current_position} azioni"
    )

    # Segnale di ACQUISTO: media veloce sopra la lenta, e non abbiamo già posizione
    if sma_fast > sma_slow and current_position == 0:
        log.info(f"SEGNALE DI ACQUISTO per {SYMBOL}")
        place_order(SYMBOL, QTY, OrderSide.BUY)

    # Segnale di VENDITA: media veloce sotto la lenta, e abbiamo posizione aperta
    elif sma_fast < sma_slow and current_position > 0:
        log.info(f"SEGNALE DI VENDITA per {SYMBOL}")
        place_order(SYMBOL, int(current_position), OrderSide.SELL)

    else:
        log.info("Nessun segnale operativo, nessuna azione.")

    return "CONTINUE"


def main():
    log.info("=== BOT DI TRADING AVVIATO (MODALITA' PAPER) ===")
    log.info(f"Titolo: {SYMBOL} | SMA veloce: {SMA_FAST} | SMA lenta: {SMA_SLOW}")

    if API_KEY.startswith("INSERISCI") or SECRET_KEY.startswith("INSERISCI"):
        log.error(
            "Devi inserire le tue API KEY di Alpaca prima di partire! "
            "Vedi le istruzioni all'inizio del file."
        )
        return

    while True:
        try:
            result = run_strategy()
            if result == "STOP":
                break
        except Exception as e:
            log.error(f"Errore durante l'esecuzione della strategia: {e}")

        log.info(f"Prossimo controllo tra {CHECK_INTERVAL_SEC // 60} minuti...")
        time.sleep(CHECK_INTERVAL_SEC)

    log.info("=== BOT FERMATO ===")


if __name__ == "__main__":
    main()
