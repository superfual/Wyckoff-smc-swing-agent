import json, sys
from datetime import datetime, timezone
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

symbol = sys.argv[1] if len(sys.argv) > 1 else 'ZECUSDT'
timeframe = sys.argv[2] if len(sys.argv) > 2 else '1H'
out = sys.argv[3] if len(sys.argv) > 3 else f'{symbol.lower()}-{timeframe.lower()}-wyckoff-smc.png'
rows = json.load(sys.stdin)
now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
rows = [r for r in rows if int(r[6]) < now_ms][-160:]
o=[float(r[1]) for r in rows]; h=[float(r[2]) for r in rows]; l=[float(r[3]) for r in rows]
c=[float(r[4]) for r in rows]; v=[float(r[5]) for r in rows]
n=len(rows); x=list(range(n))
future_x = n + 10

bg='#101214'; grid='#272b2f'; up='#6FD6BE'; down='#F28B91'; gold='#E9C46A'; cyan='#8BD3DD'; red='#F2A1A8'; blue='#8FB3D9'
fig,(ax,av)=plt.subplots(2,1,figsize=(14,8),gridspec_kw={'height_ratios':[4.2,1]},sharex=True)
fig.patch.set_facecolor(bg)
for a in (ax,av):
    a.set_facecolor(bg); a.grid(True,color=grid,alpha=.55,linewidth=.7)
    a.tick_params(colors='#c8cdd2');
    for s in a.spines.values(): s.set_color('#343a40')
ax.yaxis.tick_right(); av.yaxis.tick_right()

for i in range(n):
    col=up if c[i]>=o[i] else down
    ax.vlines(i,l[i],h[i],color=col,linewidth=1)
    low=min(o[i],c[i]); height=max(abs(c[i]-o[i]),max(c)*0.0008)
    ax.add_patch(Rectangle((i-.32,low),.64,height,facecolor=col,edgecolor=col,linewidth=.7))
    av.bar(i,v[i],width=.65,color=col,alpha=.58)

# Confirmed swing pivots (3 bars on each side)
piv_hi=[]; piv_lo=[]
for i in range(3,n-3):
    if h[i]==max(h[i-3:i+4]): piv_hi.append(i)
    if l[i]==min(l[i-3:i+4]): piv_lo.append(i)

recent_hi=piv_hi[-4:]; recent_lo=piv_lo[-4:]

# Evidence-led zones from recent confirmed pivots
if recent_hi:
    ph=recent_hi[-1]; zlo=min(o[ph],c[ph]); zhi=h[ph]
    ax.add_patch(Rectangle((ph,zlo),future_x-ph,zhi-zlo,facecolor=red,alpha=.18,edgecolor=red,linewidth=1))
    ax.text(future_x-1,zhi,f'SUPPLY {zhi:.{4 if zhi < 10 else 2}f}',color=red,ha='right',va='bottom',fontsize=10,fontweight='bold')
if recent_lo:
    pl=recent_lo[-1]; zlo=l[pl]; zhi=max(o[pl],c[pl])
    ax.add_patch(Rectangle((pl,zlo),future_x-pl,zhi-zlo,facecolor=blue,alpha=.18,edgecolor=blue,linewidth=1))
    ax.text(future_x-1,zlo,f'BOS ↓ {zlo:.{4 if zlo < 10 else 2}f}',color=cyan,ha='right',va='top',fontsize=10,fontweight='bold')

# Bias based on the latest closed price versus most recent confirmed swing levels
last=c[-1]; last_hi=h[recent_hi[-1]] if recent_hi else max(h[-30:]); last_lo=l[recent_lo[-1]] if recent_lo else min(l[-30:])
if last < last_lo:
    bias='BEARISH BOS'; bias_col=down
elif last > last_hi:
    bias='BULLISH BOS'; bias_col=up
else:
    bias='POTENTIAL DISTRIBUTION — WAIT FOR BOS'; bias_col=gold

ax.axhline(last,color='#aab2ba',linestyle=':',linewidth=1)
decimals = 4 if last < 10 else 2
ax.text(n-.4,last,f' {last:,.{decimals}f}',color='white',va='center',fontsize=11,
        bbox=dict(facecolor=bias_col,edgecolor='none',boxstyle='round,pad=.25'))
ax.text(.015,.965,f'{symbol} · {timeframe} · BINANCE SPOT',transform=ax.transAxes,color='white',fontsize=15,fontweight='bold',va='top')

# Conditional path, never presented as certainty
target=last_lo
ax.annotate('',xy=(future_x,target),xytext=(n-24,last),arrowprops=dict(arrowstyle='-|>',color=red,lw=3,alpha=.9))
ax.text(n-23,last*1.006,'IF BREAK',color=red,fontsize=9,fontweight='bold')

step=max(1,n//8)
ticks=list(range(0,n,step))
labels=[datetime.fromtimestamp(int(rows[i][0])/1000,timezone.utc).strftime('%b %d\n%H:%M') for i in ticks]
av.set_xticks(ticks); av.set_xticklabels(labels,color='#c8cdd2',fontsize=9)
av.set_ylabel('Volume',color='#c8cdd2'); ax.set_ylabel('USDT',color='#c8cdd2')
ax.set_xlim(-1,n+16); ax.set_ylim(min(l)*.965,max(h)*1.035)
plt.tight_layout()
plt.savefig(out,dpi=100,bbox_inches='tight',facecolor=fig.get_facecolor())
print(json.dumps({'file':out,'closed_candles':n,'last_close':last,'bias':bias,'swing_high':last_hi,'swing_low':last_lo}))
