import { LitElement, html, svg, css, TemplateResult, nothing } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import type { HeatSourceConfig, HeatSourceMonthly, HeatSourcePeriodStats } from "../types";
import { t, getLocale, monthShort } from "../localize";

const PALETTE = ["#4285f4", "#ea4335", "#fbbc04", "#34a853", "#ff6d01", "#46bdc6", "#9c27b0", "#795548", "#e91e63", "#3f51b5"];
const OTHER_COLOR = "#9e9e9e";
const SOLAR_OWN = "#f4b400";
const SOLAR_SOLD = "#34a853";

interface Series {
  id: string;
  name: string;
  color: string;
  kwh: number[];
  sek: number[];
}

interface SubRow {
  name: string;
  kwh: number[];
  sek: number[];
}

/** Printable yearly / 12-month electricity report for the heat sources view. */
@customElement("heat-report")
export class HeatReport extends LitElement {
  @property({ attribute: false }) hass: any;
  @property() entryId = "";
  @property({ attribute: false }) months: string[] = []; // "YYYY-MM"
  @property() periodLabel = "";
  @property({ attribute: false }) sources: HeatSourceConfig[] = [];

  @state() private _data: HeatSourceMonthly[] | null = null;
  @state() private _error = "";

  static styles = css`
    :host { display: block; }
    .toolbar { display: flex; gap: 8px; margin-bottom: 16px; }
    .toolbar button {
      padding: 6px 14px; border: 1px solid var(--divider-color, #ccc); border-radius: 6px;
      background: var(--card-background-color, #fff); color: var(--primary-text-color, #212121);
      cursor: pointer; font-size: 0.85em;
    }
    .report { color: var(--primary-text-color, #212121); font-family: var(--paper-font-body1_-_font-family, sans-serif); }
    h1 { font-size: 1.5em; margin: 0 0 4px; }
    h2 { font-size: 1.1em; margin: 0 0 12px; }
    .period { color: var(--secondary-text-color, #666); margin-bottom: 16px; }
    .kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
    .kpi { background: var(--card-background-color, #f5f5f5); border-radius: 10px; padding: 12px 16px; border: 1px solid var(--divider-color, #e0e0e0); }
    .kpi .label { font-size: 0.8em; color: var(--secondary-text-color, #666); }
    .kpi .value { font-size: 1.4em; font-weight: 600; margin-top: 4px; }
    .kpi .sub { font-size: 0.75em; color: var(--secondary-text-color, #666); margin-top: 2px; }
    .kpi.highlight { border-color: #34a853; }
    .section {
      background: var(--card-background-color, #fff); border: 1px solid var(--divider-color, #e0e0e0);
      border-radius: 10px; padding: 16px; margin-bottom: 16px; break-inside: avoid;
    }
    svg { width: 100%; height: auto; display: block; }
    svg text { fill: var(--secondary-text-color, #666); font-size: 11px; }
    .grid-line { stroke: var(--divider-color, #e0e0e0); stroke-width: 1; }
    .legend { display: flex; flex-wrap: wrap; gap: 6px 16px; margin-top: 8px; font-size: 0.8em; }
    .legend span { display: inline-flex; align-items: center; gap: 4px; }
    .swatch { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
    table { width: 100%; border-collapse: collapse; font-size: 0.78em; font-variant-numeric: tabular-nums; }
    th, td { padding: 4px 6px; text-align: right; border-bottom: 1px solid var(--divider-color, #e0e0e0); white-space: nowrap; }
    th:first-child, td:first-child { text-align: left; }
    tr.sub td { color: var(--secondary-text-color, #666); }
    tr.sub td:first-child { padding-left: 18px; }
    tr.total td { font-weight: 600; border-top: 2px solid var(--divider-color, #bbb); }
    td.sum, th.sum { font-weight: 600; }
    .footnote { font-size: 0.75em; color: var(--secondary-text-color, #666); }
    .error { color: var(--error-color, #c00); }
    @page { size: A4 landscape; margin: 10mm; }
    @media print {
      .section { border: none; padding: 0; margin-bottom: 8mm; }
      .kpi { border: 1px solid #ccc; }
    }
  `;

  private _fetchedKey = "";

  updated() {
    // The parent re-renders on every hass update and passes a new months array,
    // so compare contents — not identity — to avoid a re-fetch loop.
    const key = `${this.entryId}|${this.months.join(",")}`;
    if (this.hass && this.months.length && key !== this._fetchedKey) {
      this._fetchedKey = key;
      this._fetch();
    }
  }

  private async _fetch() {
    this._data = null;
    this._error = "";
    try {
      const result = await this.hass.callWS({
        type: "energy_facts/get_heat_source_monthly",
        entry_id: this.entryId,
        months: this.months,
      });
      this._data = result.months;
    } catch (e: any) {
      this._error = e.message || "Failed to fetch report";
    }
  }

  // ---------- data shaping ----------

  private _find(m: HeatSourceMonthly, id: string): HeatSourcePeriodStats | undefined {
    return m.heat_sources.find((s) => s.heat_source_id === id);
  }

  private _series(): Series[] {
    const data = this._data!;
    // Config order (same as cards), then any source present in data but not in config
    const ids = this.sources.map((s) => s.id);
    for (const m of data) for (const s of m.heat_sources) if (!ids.includes(s.heat_source_id)) ids.push(s.heat_source_id);
    const series: Series[] = ids.map((id, i) => {
      const name = this.sources.find((s) => s.id === id)?.name
        ?? data.flatMap((m) => m.heat_sources).find((s) => s.heat_source_id === id)?.heat_source_name ?? id;
      return {
        id,
        name,
        color: PALETTE[i % PALETTE.length],
        kwh: data.map((m) => this._find(m, id)?.total_energy_kwh ?? 0),
        sek: data.map((m) => this._find(m, id)?.total_cost_sek ?? 0),
      };
    });
    series.push({
      id: "__other",
      name: t(this.hass, "heat.other"),
      color: OTHER_COLOR,
      kwh: data.map((m) => m.other_energy_kwh ?? 0),
      sek: data.map((m) => m.other_cost_sek ?? 0),
    });
    return series;
  }

  private _subRows(id: string): SubRow[] {
    const data = this._data!;
    const sample = data.map((m) => this._find(m, id)).find((s) => s);
    if (!sample) return [];
    if (sample.has_solar) {
      return [
        {
          name: t(this.hass, "heat.solarKwh"),
          kwh: data.map((m) => this._find(m, id)?.solar_energy_kwh ?? 0),
          sek: data.map((m) => this._find(m, id)?.solar_value_sek ?? 0),
        },
        {
          name: t(this.hass, "heat.purchasedKwh"),
          kwh: data.map((m) => this._find(m, id)?.purchased_kwh ?? 0),
          sek: data.map((m) => this._find(m, id)?.purchased_cost_sek ?? 0),
        },
      ];
    }
    const compIds = new Map<string, string>();
    for (const m of data) for (const c of this._find(m, id)?.components ?? []) compIds.set(c.component_id, c.component_name);
    if (compIds.size < 2) return [];
    return [...compIds].map(([cid, name]) => ({
      name,
      kwh: data.map((m) => this._find(m, id)?.components.find((c) => c.component_id === cid)?.energy_kwh ?? 0),
      sek: data.map((m) => this._find(m, id)?.components.find((c) => c.component_id === cid)?.cost_sek ?? 0),
    }));
  }

  // ---------- formatting ----------

  private _num(v: number, digits = 0): string {
    return v.toLocaleString(getLocale(this.hass), { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  private _monthLabel(ym: string): string {
    return monthShort(this.hass, parseInt(ym.slice(5, 7), 10) - 1);
  }

  private _sum(a: number[]): number {
    return a.reduce((x, y) => x + y, 0);
  }

  // ---------- charts ----------

  private _stackedChart(layers: { color: string; values: number[] }[], unit: string): TemplateResult {
    const W = 1000, H = 296, L = 56, B = 24, T = 24;
    const n = this.months.length;
    const totals = this.months.map((_, i) => this._sum(layers.map((l) => l.values[i])));
    const max = this._niceMax(Math.max(...totals, 1));
    const plotH = H - B - T;
    const slot = (W - L) / n;
    const barW = slot * 0.65;
    const y = (v: number) => T + plotH - (v / max) * plotH;
    const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * max);
    return html`
      <svg viewBox="0 0 ${W} ${H}" role="img">
        ${ticks.map((v) => svg`
          <line class="grid-line" x1=${L} x2=${W} y1=${y(v)} y2=${y(v)}></line>
          <text x=${L - 6} y=${y(v) + 4} text-anchor="end">${this._num(v)}</text>
        `)}
        <text x="0" y="12">${unit}</text>
        ${this.months.map((ym, i) => {
          let acc = 0;
          const x = L + i * slot + (slot - barW) / 2;
          return svg`
            ${layers.map((l) => {
              const v = l.values[i];
              const top = y(acc + v);
              const h = y(acc) - top;
              acc += v;
              return v > 0 ? svg`<rect x=${x} y=${top} width=${barW} height=${h} fill=${l.color}></rect>` : nothing;
            })}
            <text x=${x + barW / 2} y=${H - 6} text-anchor="middle">${this._monthLabel(ym)}</text>
          `;
        })}
      </svg>
    `;
  }

  private _niceMax(v: number): number {
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
    return 10 * p;
  }

  private _legend(items: { name: string; color: string }[]): TemplateResult {
    return html`<div class="legend">
      ${items.map((i) => html`<span><i class="swatch" style="background:${i.color}"></i>${i.name}</span>`)}
    </div>`;
  }

  private _shareChart(series: Series[]): TemplateResult {
    const rows = series
      .map((s) => ({ ...s, total: this._sum(s.kwh) }))
      .filter((s) => s.total > 0)
      .sort((a, b) => b.total - a.total);
    const all = this._sum(rows.map((r) => r.total)) || 1;
    const W = 1000, rowH = 26, L = 220, R = 170;
    const H = rows.length * rowH + 4;
    const max = rows[0]?.total || 1;
    return html`
      <svg viewBox="0 0 ${W} ${H}" role="img">
        ${rows.map((r, i) => {
          const w = ((W - L - R) * r.total) / max;
          const yy = i * rowH + 4;
          return svg`
            <text x=${L - 8} y=${yy + 15} text-anchor="end">${r.name}</text>
            <rect x=${L} y=${yy} width=${w} height=${rowH - 8} fill=${r.color} rx="2"></rect>
            <text x=${L + w + 8} y=${yy + 15}>${this._num(r.total)} kWh · ${this._num((r.total / all) * 100, 1)} %</text>
          `;
        })}
      </svg>
    `;
  }

  // ---------- tables ----------

  private _table(series: Series[], kind: "kwh" | "sek", houseTotal: number[]): TemplateResult {
    const priceCol = kind === "sek";
    const cells = (vals: number[], energy?: number[]) => html`
      ${vals.map((v) => html`<td>${this._num(v)}</td>`)}
      <td class="sum">${this._num(this._sum(vals))}</td>
      ${priceCol ? html`<td>${energy && this._sum(energy) > 0 ? this._num(this._sum(vals) / this._sum(energy), 2) : "–"}</td>` : nothing}
    `;
    const houseKwh = this._data!.map((m) => m.house_energy_kwh ?? 0);
    return html`
      <table>
        <thead>
          <tr>
            <th>${t(this.hass, "report.consumer")}</th>
            ${this.months.map((ym) => html`<th>${this._monthLabel(ym)}</th>`)}
            <th class="sum">${t(this.hass, "report.total")}</th>
            ${priceCol ? html`<th>${t(this.hass, "report.pricePerKwh")}</th>` : nothing}
          </tr>
        </thead>
        <tbody>
          ${series.map((s) => html`
            <tr>
              <td><i class="swatch" style="background:${s.color}"></i> ${s.name}</td>
              ${cells(kind === "kwh" ? s.kwh : s.sek, s.kwh)}
            </tr>
            ${s.id === "__other" ? nothing : this._subRows(s.id).map((r) => html`
              <tr class="sub">
                <td>${r.name}</td>
                ${cells(kind === "kwh" ? r.kwh : r.sek, r.kwh)}
              </tr>
            `)}
          `)}
          <tr class="total">
            <td>${t(this.hass, "report.houseTotal")}</td>
            ${cells(houseTotal, houseKwh)}
          </tr>
        </tbody>
      </table>
    `;
  }

  // ---------- print ----------

  private _print() {
    const report = this.renderRoot.querySelector(".report");
    if (!report) return;
    const css = (this.constructor as typeof HeatReport).styles as any;
    const iframe = document.createElement("iframe");
    iframe.style.cssText = "position:fixed;width:0;height:0;border:0;right:0;bottom:0";
    document.body.appendChild(iframe);
    const doc = iframe.contentDocument!;
    doc.open();
    doc.write(`<!doctype html><html><head><meta charset="utf-8"><title>${t(this.hass, "report.title")} ${this.periodLabel}</title>`
      + `<style>body{margin:0;font-family:sans-serif;-webkit-print-color-adjust:exact;print-color-adjust:exact}${css.cssText}</style>`
      + `</head><body>${report.outerHTML}</body></html>`);
    doc.close();
    setTimeout(() => {
      iframe.contentWindow!.focus();
      iframe.contentWindow!.print();
      setTimeout(() => iframe.remove(), 1000);
    }, 100);
  }

  // ---------- render ----------

  render(): TemplateResult {
    const toolbar = html`
      <div class="toolbar">
        <button @click=${() => this.dispatchEvent(new CustomEvent("close"))}>← ${t(this.hass, "report.back")}</button>
        <button @click=${this._print} ?disabled=${!this._data}>${t(this.hass, "report.print")}</button>
      </div>
    `;
    if (this._error) return html`${toolbar}<div class="error">${this._error}</div>`;
    if (!this._data) return html`${toolbar}<div>${t(this.hass, "common.loading")}</div>`;

    const data = this._data;
    const series = this._series();
    const houseKwh = data.map((m) => m.house_energy_kwh ?? 0);
    const houseSek = data.map((m) => m.house_cost_sek ?? 0);
    const totalKwh = this._sum(houseKwh);
    const totalSek = this._sum(houseSek);
    const own = data.map((m) => m.solar_own_use_kwh ?? 0);
    const sold = data.map((m) => m.solar_sold_kwh ?? 0);
    const solarShare = totalKwh > 0 ? (this._sum(own) / totalKwh) * 100 : 0;
    const tot = (k: keyof HeatSourceMonthly) => this._sum(data.map((m) => (m[k] as number) ?? 0));
    const boughtKwh = tot("purchased_kwh");
    const boughtSek = tot("purchased_cost_sek");
    const avoided = tot("own_use_avoided_sek");
    const saving = avoided - tot("own_use_alt_income_sek");
    const ownKwh = this._sum(own);
    const kpi = (label: string, value: string, sub = "", cls = "") =>
      html`<div class="kpi ${cls}"><div class="label">${label}</div><div class="value">${value}</div>${sub ? html`<div class="sub">${sub}</div>` : nothing}</div>`;
    const legend = this._legend(series);

    return html`
      ${toolbar}
      <div class="report">
        <h1>${t(this.hass, "report.title")}</h1>
        <div class="period">${this.periodLabel}</div>

        <div class="kpis">
          ${kpi(t(this.hass, "report.totalEnergy"), `${this._num(totalKwh)} kWh`)}
          ${kpi(t(this.hass, "report.purchasedEnergy"), `${this._num(boughtKwh)} kWh`)}
          ${kpi(t(this.hass, "report.ownSolarEnergy"), `${this._num(ownKwh)} kWh`, `${this._num(solarShare, 1)} % ${t(this.hass, "report.ofConsumption")}`)}
          ${kpi(t(this.hass, "report.solarSold"), `${this._num(this._sum(sold))} kWh`)}
        </div>
        <div class="kpis">
          ${kpi(t(this.hass, "report.totalCost"), `${this._num(totalSek)} SEK`, `${totalKwh > 0 ? this._num(totalSek / totalKwh, 2) : "–"} kr/kWh`)}
          ${kpi(t(this.hass, "report.purchasedCost"), `${this._num(boughtSek)} SEK`, `${boughtKwh > 0 ? this._num(boughtSek / boughtKwh, 2) : "–"} kr/kWh`)}
          ${kpi(t(this.hass, "report.ownSolarValue"), `${this._num(avoided)} SEK`, t(this.hass, "report.ownSolarValueSub"))}
          ${kpi(t(this.hass, "report.saving"), `${this._num(saving)} SEK`, `${ownKwh > 0 ? this._num(saving / ownKwh, 2) : "–"} kr/kWh ${t(this.hass, "report.savingSub")}`, "highlight")}
        </div>

        <div class="section">
          <h2>${t(this.hass, "report.kwhPerMonth")}</h2>
          ${this._stackedChart(series.map((s) => ({ color: s.color, values: s.kwh })), "kWh")}
          ${legend}
        </div>

        <div class="section">
          <h2>${t(this.hass, "report.costPerMonth")}</h2>
          ${this._stackedChart(series.map((s) => ({ color: s.color, values: s.sek })), "SEK")}
          ${legend}
        </div>

        <div class="section">
          <h2>${t(this.hass, "report.share")}</h2>
          ${this._shareChart(series)}
        </div>

        <div class="section">
          <h2>${t(this.hass, "report.solar")}</h2>
          ${this._stackedChart([{ color: SOLAR_OWN, values: own }, { color: SOLAR_SOLD, values: sold }], "kWh")}
          ${this._legend([
            { name: `${t(this.hass, "report.solarOwnUse")} (${this._num(this._sum(own))} kWh)`, color: SOLAR_OWN },
            { name: `${t(this.hass, "report.solarSold")} (${this._num(this._sum(sold))} kWh)`, color: SOLAR_SOLD },
          ])}
        </div>

        <div class="section">
          <h2>${t(this.hass, "report.tableKwh")}</h2>
          ${this._table(series, "kwh", houseKwh)}
        </div>

        <div class="section">
          <h2>${t(this.hass, "report.tableCost")}</h2>
          ${this._table(series, "sek", houseSek)}
        </div>

        <p class="footnote">${t(this.hass, "report.footnote")}</p>
      </div>
    `;
  }
}
