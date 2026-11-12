"""Render verified Binance Futures OHLCV as a self-contained SVG chart.

No fabricated price bars or trade levels. Standard-library only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from pathlib import Path

_TIMEFRAME = {"D1": "daily", "H4": "four_hour", "H1": "one_hour", "M15": "fifteen_minute"}


def render_chart(market, timeframe: str, output: str | Path, *, status: str = "NO CLEAR EDGE", candles_to_show: int = 100) -> Path:
    tf = timeframe.upper()
    if tf not in _TIMEFRAME:
        raise ValueError("Unsupported chart timeframe")
    bars = getattr(market, _TIMEFRAME[tf])[-candles_to_show:]
    if not bars:
        raise ValueError("NO_CLOSED_CANDLES_FOR_CHART")
    width, height = 1600, 900
    left, right, top, bottom = 90, 1450, 120, 720
    low = min(c.low for c in bars)
    high = max(c.high for c in bars)
    span = max(high - low, high * .001)
    low -= span * .08
    high += span * .08
    def y(v):
        return bottom - (v - low) / (high - low) * (bottom - top)
    dx = (right - left) / len(bars)
    shapes = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">',
        '<rect width="1600" height="900" fill="#101820"/>',
        '<text x="90" y="60" fill="#f1f5f9" font-size="33" font-family="Arial" font-weight="bold">'
        + escape(market.symbol) + ' · ' + escape(tf) + '</text>',
        '<text x="90" y="95" fill="#91a6b7" font-size="18" font-family="Arial">BINANCE USD-M FUTURES · VERIFIED CLOSED CANDLES</text>',
        '<text x="1450" y="65" text-anchor="end" fill="#f4bd70" font-size="23" font-family="Arial">'
        + escape(status) + '</text>',
    ]
    for i in range(6):
        price = low + (high - low) * i / 5
        yy = y(price)
        shapes.append(f'<line x1="{left}" y1="{yy:.2f}" x2="{right}" y2="{yy:.2f}" stroke="#2b3a46" stroke-dasharray="4 7"/>')
        shapes.append(f'<text x="1470" y="{yy+6:.2f}" fill="#a4b5c2" font-size="18" font-family="Arial">{price:,.3f}</text>')
    for i, c in enumerate(bars):
        x = left + dx * (i + .5)
        color = "#59d2b6" if c.close >= c.open else "#ed8289"
        shapes.append(f'<line x1="{x:.2f}" y1="{y(c.high):.2f}" x2="{x:.2f}" y2="{y(c.low):.2f}" stroke="{color}" stroke-width="2"/>')
        yy = min(y(c.open), y(c.close))
        hh = max(abs(y(c.open) - y(c.close)), 1.6)
        shapes.append(f'<rect x="{x-dx*.3:.2f}" y="{yy:.2f}" width="{dx*.6:.2f}" height="{hh:.2f}" fill="{color}"/>')
    for i in range(0, len(bars), max(1, len(bars)//7)):
        x = left + dx * (i + .5)
        stamp = datetime.fromtimestamp(bars[i].timestamp / 1000, timezone.utc).strftime("%d %b %H:%M")
        shapes.append(f'<text x="{x:.1f}" y="758" fill="#8ea1b1" font-size="17" font-family="Arial">{stamp}</text>')
    shapes.append(f'<text x="90" y="820" fill="#b4c3ce" font-size="20" font-family="Arial">Last closed: {bars[-1].close:,.4f} USDT  ·  {len(bars)} candles shown</text>')
    shapes.append('<text x="90" y="858" fill="#8ea1b1" font-size="17" font-family="Arial">Research only · No synthetic candles · No entry/SL/TP without validated thesis</text>')
    shapes.append('</svg>')
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(shapes), encoding="utf-8")
    return path
