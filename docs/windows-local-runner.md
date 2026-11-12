# One-click Windows Local Futures Analyst

Use this only on your own Windows computer while it is powered on.
No Binance keys, trading credentials, server or GitHub-hosted runner needed.

## First-time setup
1. Install Python 3.11+ from python.org. Check `py -3 --version` in Command Prompt.
2. Download the repository ZIP from GitHub Code > Download ZIP and extract it.
   Alternatively, `git clone https://github.com/superfual/Wyckoff-smc-swing-agent.git`.
3. Double-click `RUN_LOCAL_WINDOWS.bat` in the extracted repository folder.
4. Press Enter for BTCUSDT or enter another USD-M USDT Futures symbol (for example ZECUSDT).
5. Read the console and open `reports/public_futures_signal.json`.

## How it works
- Collects 1D, 4H, 1H and 15M closed candles from official Binance USD-M Futures public endpoints.
- Validates exact candle counts and timestamps; rejects missing, stale, malformed or future data.
- Uses existing Wyckoff-SMC engine; produces a read-only research report.
- On any API/data failure, reports DATA_UNAVAILABLE rather than inventing a signal.
- Uses an illustrative 10,000 USDT NAV, not the user's actual account.
- Runs once per double-click. It does not install startup tasks or background processes.
- Requires internet connectivity. Windows and Python must be allowed outbound HTTPS access.

## Troubleshooting
- If `py` or `python` is missing, install Python 3.11+ and restart Command Prompt.
- If the local collector receives HTTP 451 or 403, do not attempt to bypass access restrictions.
- If you see DATA_UNAVAILABLE, do not use the output as a trading signal.
- This script does not automatically send reports to ChatGPT. Share the JSON if you want a second review.
