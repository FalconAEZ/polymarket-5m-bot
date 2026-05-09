"""Browser-side provider RTT configuration for the v2 health column.

The actual RTT measurement happens client-side in JavaScript injected
via st.components.v1.html — Python's role here is to assemble the
provider list and render the JS snippet. Browser RTT is *not* the bot's
RTT; the bot is in Dublin, the operator is wherever they are. Every
panel that uses these readings must label the limitation.

Bot-side per-message RTT requires a one-line hook in src/polymarket_bot/
feeds/* — out of scope for this dashboard pass; lands as a separate
follow-up commit per design/dashboard-v2.md §10.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    name: str
    url: str
    expects_json: bool


PROVIDERS: tuple[ProviderConfig, ...] = (
    ProviderConfig("Binance", "https://api.binance.com/api/v3/time", expects_json=True),
    ProviderConfig("Coinbase", "https://api.exchange.coinbase.com/time", expects_json=True),
    ProviderConfig("Chainlink", "https://eth.llamarpc.com", expects_json=True),
    ProviderConfig(
        "PM-Gamma", "https://gamma-api.polymarket.com/markets?limit=1", expects_json=True
    ),
    ProviderConfig("PM-CLOB", "https://clob.polymarket.com/", expects_json=False),
)

SAMPLE_INTERVAL_MS: int = 10_000  # one ping per provider per 10s
HISTORY_LENGTH: int = 6  # 60s of samples at 10s cadence


def provider_rtt_config() -> list[ProviderConfig]:
    return list(PROVIDERS)


def _providers_as_dicts() -> list[dict[str, str | bool]]:
    return [{"name": p.name, "url": p.url, "expects_json": p.expects_json} for p in PROVIDERS]


def rtt_widget_html(*, container_id: str = "pmb-rtt") -> str:
    """Returns the inline HTML+JS that runs the RTT measurement loop.

    Embed via st.components.v1.html(rtt_widget_html(), height=320). The
    widget renders inline mini-bars per provider into the given
    container_id and persists samples in localStorage so a refresh
    doesn't lose the 60s history. Each row labels itself with the
    'measured from this laptop' caveat once at the top.
    """
    providers_json = json.dumps(_providers_as_dicts())
    return f"""
<div id=\"{container_id}\" class=\"pmb-rtt\">
  <div class=\"pmb-rtt__caveat\">RTT measured from this laptop, not from the bot's VPS.</div>
  <div class=\"pmb-rtt__rows\"></div>
</div>
<style>
  .pmb-rtt {{ font-family: 'JetBrains Mono', ui-monospace, monospace; color: #f5edd6; padding: 8px; }}
  .pmb-rtt__caveat {{ font-size: 9px; color: #5a4f3a; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px; }}
  .pmb-rtt__row {{ display: flex; align-items: center; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #2a261c; }}
  .pmb-rtt__row:last-child {{ border-bottom: none; }}
  .pmb-rtt__name {{ font-size: 10px; color: #9c8d6b; text-transform: uppercase; letter-spacing: 0.08em; min-width: 64px; }}
  .pmb-rtt__bars {{ display: flex; align-items: flex-end; gap: 1px; height: 18px; flex: 1; margin: 0 8px; }}
  .pmb-rtt__bar {{ flex: 1; background: #2a261c; border-radius: 1px; min-height: 2px; transition: height 200ms ease, background 200ms ease; }}
  .pmb-rtt__bar--good {{ background: #8aff7a; }}
  .pmb-rtt__bar--warn {{ background: #ffb84a; }}
  .pmb-rtt__bar--bad {{ background: #ff5c5c; }}
  .pmb-rtt__value {{ font-size: 11px; font-variant-numeric: tabular-nums; min-width: 56px; text-align: right; }}
  .pmb-rtt__value--err {{ color: #ff5c5c; }}
</style>
<script>
(function() {{
  const PROVIDERS = {providers_json};
  const HISTORY = {HISTORY_LENGTH};
  const INTERVAL = {SAMPLE_INTERVAL_MS};
  const KEY = 'pmb_rtt_history_v1';
  const container = document.getElementById('{container_id}').querySelector('.pmb-rtt__rows');

  function loadHistory() {{
    try {{ return JSON.parse(localStorage.getItem(KEY) || '{{}}'); }} catch (e) {{ return {{}}; }}
  }}
  function saveHistory(h) {{
    try {{ localStorage.setItem(KEY, JSON.stringify(h)); }} catch (e) {{}}
  }}
  let history = loadHistory();

  function ensureRow(name) {{
    let row = container.querySelector('[data-name="' + name + '"]');
    if (!row) {{
      row = document.createElement('div');
      row.className = 'pmb-rtt__row';
      row.dataset.name = name;
      row.innerHTML = '<div class="pmb-rtt__name">' + name + '</div>'
        + '<div class="pmb-rtt__bars"></div>'
        + '<div class="pmb-rtt__value">—</div>';
      container.appendChild(row);
    }}
    return row;
  }}

  function classify(ms) {{
    if (ms === null) return 'bad';
    if (ms < 200) return 'good';
    if (ms < 600) return 'warn';
    return 'bad';
  }}

  function render(name, samples) {{
    const row = ensureRow(name);
    const bars = row.querySelector('.pmb-rtt__bars');
    const value = row.querySelector('.pmb-rtt__value');
    bars.innerHTML = '';
    const padded = samples.slice(-HISTORY);
    while (padded.length < HISTORY) padded.unshift(null);
    const max = Math.max(...padded.filter(v => v !== null), 100);
    padded.forEach(ms => {{
      const bar = document.createElement('div');
      bar.className = 'pmb-rtt__bar pmb-rtt__bar--' + classify(ms);
      const h = ms === null ? 2 : Math.max(2, Math.min(18, (ms / max) * 18));
      bar.style.height = h + 'px';
      bars.appendChild(bar);
    }});
    const last = samples[samples.length - 1];
    if (last === null || last === undefined) {{
      value.textContent = 'err';
      value.classList.add('pmb-rtt__value--err');
    }} else {{
      value.textContent = Math.round(last) + 'ms';
      value.classList.remove('pmb-rtt__value--err');
    }}
  }}

  async function ping(provider) {{
    const start = performance.now();
    try {{
      const resp = await fetch(provider.url, {{ method: 'GET', cache: 'no-store', mode: 'cors' }});
      // For non-JSON endpoints we just need the headers to come back.
      if (provider.expects_json) {{ await resp.text(); }}
      return performance.now() - start;
    }} catch (e) {{
      return null;
    }}
  }}

  async function tick() {{
    for (const p of PROVIDERS) {{
      const ms = await ping(p);
      const samples = history[p.name] || [];
      samples.push(ms);
      while (samples.length > HISTORY) samples.shift();
      history[p.name] = samples;
      render(p.name, samples);
    }}
    saveHistory(history);
  }}

  PROVIDERS.forEach(p => render(p.name, history[p.name] || []));
  tick();
  setInterval(tick, INTERVAL);
}})();
</script>
"""
