"""Rate-limit-aware, read-only Binance Spot watchlist acquisition.

The runner deliberately depends on only two market-data methods: ``get_price``
and ``get_klines``. It has no account, wallet, transfer, credential or order
surface. Successful endpoint responses are cached while transient failures are
retried individually with bounded backoff.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from time import sleep
from typing import Any, Callable, Mapping, Protocol, Sequence

try:
    from .market_data import MarketData, build_market_data, normalize_price
    from .scanner import WatchlistSymbol
    from .watchlist_validation import WatchlistValidationResult, validate_watchlist_batch
except ImportError:
    from market_data import MarketData, build_market_data, normalize_price
    from scanner import WatchlistSymbol
    from watchlist_validation import WatchlistValidationResult, validate_watchlist_batch


HOUR_MS = 3_600_000
_REQUESTS = (
    ("price", None, 1),
    ("1D", "1d", 120),
    ("4H", "4h", 240),
    ("1H", "1h", 300),
    ("15M", "15m", 300),
)
_TRANSIENT_TOKENS = (
    "-1003",
    "429",
    "RATE_LIMIT",
    "TOO MUCH REQUEST WEIGHT",
    "TIMEOUT",
    "TIMED OUT",
    "TEMPORARILY UNAVAILABLE",
    "UNAVAILABLE",
    "CONNECTION",
)


class ReadOnlySpotClient(Protocol):
    def get_price(self, symbol: str) -> Any: ...

    def get_klines(
        self,
        symbol: str,
        interval: str,
        *,
        limit: int,
        end_time: int,
    ) -> list[list[Any]]: ...


@dataclass(frozen=True)
class BinanceWatchlistAcquisitionConfig:
    symbols_per_group: int = 3
    max_attempts: int = 3
    initial_backoff_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 8.0
    group_pause_seconds: float = 0.0


@dataclass(frozen=True)
class AcquisitionFailure:
    symbol: str
    request: str
    attempts: int
    retryable: bool
    code: str


@dataclass
class BinanceWatchlistAcquisition:
    captured_at: int
    decision_time: int
    complete: bool
    expected_symbols: list[str]
    completed_symbols: list[str]
    incomplete_symbols: list[str]
    markets: list[MarketData]
    observed_prices: dict[str, float]
    attempts: dict[str, int]
    failures: list[AcquisitionFailure]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BinanceWatchlistPipelineResult:
    acquisition: BinanceWatchlistAcquisition
    validation: WatchlistValidationResult | None
    status: str

    def to_dict(self) -> dict:
        return asdict(self)


def aligned_hour_decision_time(captured_at: int) -> int:
    if captured_at < 0:
        raise ValueError("captured_at must be >= 0")
    return captured_at // HOUR_MS * HOUR_MS


def _validate_config(config: BinanceWatchlistAcquisitionConfig) -> None:
    if config.symbols_per_group < 1 or config.max_attempts < 1:
        raise ValueError("symbols_per_group and max_attempts must be >= 1")
    if config.initial_backoff_seconds < 0 or config.group_pause_seconds < 0:
        raise ValueError("backoff and group pause must be >= 0")
    if config.backoff_multiplier < 1 or config.max_backoff_seconds < 0:
        raise ValueError("invalid backoff configuration")


def _error_text(error: BaseException) -> str:
    code = getattr(error, "code", "")
    detail = getattr(error, "detail", "")
    return f"{code} {detail} {type(error).__name__} {error}".upper()


def is_transient_binance_error(error: BaseException) -> bool:
    text = _error_text(error)
    return any(token in text for token in _TRANSIENT_TOKENS)


def _failure_code(error: BaseException, retryable: bool) -> str:
    explicit = getattr(error, "code", None)
    if isinstance(explicit, str) and explicit:
        return explicit
    return "TRANSIENT_BINANCE_ERROR" if retryable else f"PERMANENT_{type(error).__name__.upper()}"


def _validate_klines(value: Any) -> list[list[Any]]:
    if not isinstance(value, list):
        raise ValueError("INVALID_KLINE_RESPONSE")
    if any(not isinstance(row, (list, tuple)) or len(row) < 6 for row in value):
        raise ValueError("INVALID_KLINE_RESPONSE")
    return [list(row) for row in value]


def _request(
    client: ReadOnlySpotClient,
    symbol: str,
    request: str,
    interval: str | None,
    limit: int,
    decision_time: int,
) -> Any:
    if request == "price":
        value = normalize_price(client.get_price(symbol))
        if value is None or value <= 0:
            raise ValueError("INVALID_PRICE_RESPONSE")
        return value
    return _validate_klines(
        client.get_klines(symbol, interval or "", limit=limit, end_time=decision_time)
    )


def acquire_binance_watchlist(
    client: ReadOnlySpotClient,
    watchlist: Sequence[WatchlistSymbol],
    *,
    captured_at: int,
    config: BinanceWatchlistAcquisitionConfig | None = None,
    sleep_fn: Callable[[float], None] = sleep,
) -> BinanceWatchlistAcquisition:
    """Acquire one immutable multi-symbol snapshot with bounded retries."""

    cfg = config or BinanceWatchlistAcquisitionConfig()
    _validate_config(cfg)
    decision_time = aligned_hour_decision_time(captured_at)
    normalized = [WatchlistSymbol(item.symbol.upper().strip(), item.priority.upper().strip()) for item in watchlist]
    symbols = [item.symbol for item in normalized]
    if not symbols or any(not symbol.endswith("USDT") for symbol in symbols) or len(set(symbols)) != len(symbols):
        raise ValueError("watchlist must contain unique USDT symbols")

    cache: dict[tuple[str, str], Any] = {}
    attempts: dict[str, int] = {}
    failures: list[AcquisitionFailure] = []

    for group_start in range(0, len(symbols), cfg.symbols_per_group):
        group = symbols[group_start:group_start + cfg.symbols_per_group]
        for symbol in group:
            for request, interval, limit in _REQUESTS:
                key = (symbol, request)
                attempt_key = f"{symbol}:{request}"
                backoff = cfg.initial_backoff_seconds
                last_error: BaseException | None = None
                for attempt in range(1, cfg.max_attempts + 1):
                    attempts[attempt_key] = attempt
                    try:
                        cache[key] = _request(client, symbol, request, interval, limit, decision_time)
                        last_error = None
                        break
                    except Exception as error:  # fail closed at the injected transport boundary
                        last_error = error
                        retryable = is_transient_binance_error(error)
                        if not retryable or attempt == cfg.max_attempts:
                            break
                        sleep_fn(min(backoff, cfg.max_backoff_seconds))
                        backoff *= cfg.backoff_multiplier
                if last_error is not None:
                    retryable = is_transient_binance_error(last_error)
                    failures.append(AcquisitionFailure(
                        symbol=symbol,
                        request=request,
                        attempts=attempts[attempt_key],
                        retryable=retryable,
                        code=_failure_code(last_error, retryable),
                    ))
        if group_start + cfg.symbols_per_group < len(symbols) and cfg.group_pause_seconds:
            sleep_fn(cfg.group_pause_seconds)

    markets: list[MarketData] = []
    prices: dict[str, float] = {}
    completed: list[str] = []
    incomplete: list[str] = []
    for symbol in symbols:
        if any((symbol, request) not in cache for request, _, _ in _REQUESTS):
            incomplete.append(symbol)
            continue
        try:
            prices[symbol] = cache[(symbol, "price")]
            markets.append(build_market_data(
                symbol,
                prices[symbol],
                cache[(symbol, "1D")],
                cache[(symbol, "4H")],
                cache[(symbol, "1H")],
                cache[(symbol, "15M")],
            ))
            completed.append(symbol)
        except (TypeError, ValueError, IndexError) as error:
            incomplete.append(symbol)
            failures.append(AcquisitionFailure(
                symbol, "normalization", 1, False, _failure_code(error, False)
            ))
            prices.pop(symbol, None)

    return BinanceWatchlistAcquisition(
        captured_at=captured_at,
        decision_time=decision_time,
        complete=not incomplete and not failures,
        expected_symbols=symbols,
        completed_symbols=completed,
        incomplete_symbols=incomplete,
        markets=markets,
        observed_prices=prices,
        attempts=attempts,
        failures=failures,
    )


def acquire_and_validate_watchlist(
    client: ReadOnlySpotClient,
    watchlist: Sequence[WatchlistSymbol],
    *,
    captured_at: int,
    account_equity: float = 10_000.0,
    acquisition_config: BinanceWatchlistAcquisitionConfig | None = None,
    sleep_fn: Callable[[float], None] = sleep,
) -> BinanceWatchlistPipelineResult:
    acquisition = acquire_binance_watchlist(
        client,
        watchlist,
        captured_at=captured_at,
        config=acquisition_config,
        sleep_fn=sleep_fn,
    )
    if not acquisition.complete:
        return BinanceWatchlistPipelineResult(acquisition, None, "INCOMPLETE")
    validation = validate_watchlist_batch(
        acquisition.markets,
        watchlist,
        decision_time=acquisition.decision_time,
        observed_prices=acquisition.observed_prices,
        account_equity=account_equity,
    )
    return BinanceWatchlistPipelineResult(
        acquisition,
        validation,
        "READY" if validation.ready else "BLOCKED",
    )
