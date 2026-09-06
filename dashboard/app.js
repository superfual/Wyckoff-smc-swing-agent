const rows = [
  ["BTCUSDT",83,"HIGH_INTEREST","BLOCKED"],
  ["XRPUSDT",83,"HIGH_INTEREST","BLOCKED"],
  ["ETHUSDT",77,"HIGH_INTEREST","BLOCKED"],
  ["ADAUSDT",77,"HIGH_INTEREST","BLOCKED"],
  ["LINKUSDT",76,"HIGH_INTEREST","BLOCKED"],
  ["SOLUSDT",71,"WATCH","BLOCKED"],
  ["AVAXUSDT",70,"WATCH","BLOCKED"],
  ["SUIUSDT",70,"WATCH","BLOCKED"],
  ["BNBUSDT",65,"WATCH","BLOCKED"],
  ["DOGEUSDT",60,"WATCH","BLOCKED"],
  ["UNIUSDT",60,"WATCH","BLOCKED"],
  ["AAVEUSDT",53,"NEUTRAL","SCANNED_ONLY"]
];

const body = document.querySelector("#ranking-body");
rows.forEach(([symbol, score, interest, action], index) => {
  const tr = document.createElement("tr");
  const tagClass = interest === "HIGH_INTEREST" ? "high" : interest === "WATCH" ? "watch" : "neutral";
  const actionClass = action === "BLOCKED" ? "blocked" : "scanned";
  tr.innerHTML = `<td>${String(index + 1).padStart(2, "0")}</td>
    <td class="asset">${symbol}</td>
    <td><span class="tag ${tagClass}">${interest}</span></td>
    <td><span class="score-cell"><span class="bar"><i style="width:${score}%"></i></span>${score}</span></td>
    <td class="${actionClass}">${action}</td>`;
  body.appendChild(tr);
});
