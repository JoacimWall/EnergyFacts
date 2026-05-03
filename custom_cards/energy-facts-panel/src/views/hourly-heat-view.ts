import { LitElement, html, TemplateResult } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import { cardStyles, tableStyles } from "../styles";
import { HourlyHeatRecord, HeatSourceConfig } from "../types";
import { t, getLang } from "../localize";

const PAGE_SIZE = 50;

@customElement("hourly-heat-view")
export class HourlyHeatView extends LitElement {
  @property({ attribute: false }) hass: any;
  @property() entryId = "";

  @state() private _startDate = "";
  @state() private _endDate = "";
  @state() private _records: HourlyHeatRecord[] = [];
  @state() private _totalCount = 0;
  @state() private _offset = 0;
  @state() private _loading = false;
  @state() private _error = "";
  @state() private _heatSources: HeatSourceConfig[] = [];
  @state() private _selectedSourceId = "";

  static styles = [cardStyles, tableStyles];

  connectedCallback() {
    super.connectedCallback();
    const today = new Date().toISOString().substring(0, 10);
    this._startDate = today;
    this._endDate = today;
    this._loadHeatSources();
  }

  render(): TemplateResult {
    return html`
      <div class="card">
        <h3>${t(this.hass, "hourlyHeat.title")}</h3>
        <div class="table-controls">
          <div class="input-group">
            <label>${t(this.hass, "hourly.startDate")}</label>
            <input
              type="date"
              .value=${this._startDate}
              @change=${(e: Event) => {
                this._startDate = (e.target as HTMLInputElement).value;
              }}
            />
          </div>
          <div class="input-group">
            <label>${t(this.hass, "hourly.endDate")}</label>
            <input
              type="date"
              .value=${this._endDate}
              @change=${(e: Event) => {
                this._endDate = (e.target as HTMLInputElement).value;
              }}
            />
          </div>
          <div class="input-group">
            <label>${t(this.hass, "hourlyHeat.heatSource")}</label>
            <select @change=${(e: Event) => {
              this._selectedSourceId = (e.target as HTMLSelectElement).value;
            }}>
              <option value="">${t(this.hass, "hourlyHeat.allSources")}</option>
              ${this._heatSources.map(
                (s) => html`<option value=${s.id} ?selected=${this._selectedSourceId === s.id}>${s.name}</option>`
              )}
            </select>
          </div>
          <button class="btn" @click=${this._fetch} ?disabled=${this._loading}>
            ${this._loading ? t(this.hass, "hourly.loadingBtn") : t(this.hass, "hourly.loadBtn")}
          </button>
        </div>

        ${this._error
          ? html`<div class="no-data">${t(this.hass, "common.error")}: ${this._error}</div>`
          : ""}
        ${this._records.length > 0 ? this._renderTable() : ""}
        ${!this._loading && this._records.length === 0 && !this._error
          ? html`<div class="no-data">
              ${t(this.hass, "hourly.selectDateRange")}
            </div>`
          : ""}
      </div>
    `;
  }

  private _renderTable(): TemplateResult {
    const totalPages = Math.ceil(this._totalCount / PAGE_SIZE);
    const currentPage = Math.floor(this._offset / PAGE_SIZE) + 1;

    return html`
      <div class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>${t(this.hass, "hourly.timestamp")}</th>
              <th>${t(this.hass, "hourlyHeat.heatSource")}</th>
              <th>${t(this.hass, "hourlyHeat.component")}</th>
              <th>${t(this.hass, "hourlyHeat.energyKwh")}</th>
              <th>${t(this.hass, "hourlyHeat.costSek")}</th>
              <th>${t(this.hass, "hourlyHeat.avgPower")}</th>
              <th>${t(this.hass, "hourlyHeat.spotPrice")}</th>
              <th>${t(this.hass, "hourlyHeat.samples")}</th>
            </tr>
          </thead>
          <tbody>
            ${this._records.map(
              (r) => html`
                <tr>
                  <td>${this._formatTs(r.timestamp)}</td>
                  <td>${this._sourceName(r.heat_source_id)}</td>
                  <td>${this._componentName(r.component)}</td>
                  <td>${r.energy_kwh.toFixed(4)}</td>
                  <td>${r.cost_sek.toFixed(2)}</td>
                  <td>${r.avg_power_w.toFixed(1)}</td>
                  <td>${r.spot_price.toFixed(4)}</td>
                  <td>${r.samples}</td>
                </tr>
              `
            )}
          </tbody>
        </table>
      </div>
      <div class="pagination">
        <button
          class="btn"
          ?disabled=${this._offset === 0 || this._loading}
          @click=${this._prevPage}
        >
          ${t(this.hass, "hourly.prev")}
        </button>
        <span>${t(this.hass, "hourly.pageInfo", currentPage, totalPages, this._totalCount)}</span>
        <button
          class="btn"
          ?disabled=${this._offset + PAGE_SIZE >= this._totalCount || this._loading}
          @click=${this._nextPage}
        >
          ${t(this.hass, "hourly.next")}
        </button>
      </div>
    `;
  }

  private async _loadHeatSources() {
    if (!this.hass || !this.entryId) return;
    try {
      const result = await this.hass.callWS({
        type: "energy_facts/get_heat_sources",
        entry_id: this.entryId,
      });
      this._heatSources = result.heat_sources || [];
    } catch {
      // Silently ignore — dropdown will just be empty
    }
  }

  private async _fetch() {
    if (!this.hass || !this.entryId || !this._startDate || !this._endDate)
      return;
    this._loading = true;
    this._error = "";
    try {
      const start = `${this._startDate}T00:00:00`;
      const endDate = new Date(this._endDate);
      endDate.setDate(endDate.getDate() + 1);
      const end = `${endDate.toISOString().substring(0, 10)}T00:00:00`;

      const msg: any = {
        type: "energy_facts/get_hourly_heat",
        entry_id: this.entryId,
        start_date: start,
        end_date: end,
        offset: this._offset,
        limit: PAGE_SIZE,
      };
      if (this._selectedSourceId) {
        msg.heat_source_id = this._selectedSourceId;
      }

      const result = await this.hass.callWS(msg);
      this._records = result.records;
      this._totalCount = result.total_count;
    } catch (e: any) {
      this._error = e.message || "Failed to fetch data";
      this._records = [];
      this._totalCount = 0;
    }
    this._loading = false;
  }

  private _prevPage() {
    this._offset = Math.max(0, this._offset - PAGE_SIZE);
    this._fetch();
  }

  private _nextPage() {
    this._offset += PAGE_SIZE;
    this._fetch();
  }

  private _formatTs(ts: string): string {
    try {
      return ts.replace("T", " ").substring(0, 19);
    } catch {
      return ts;
    }
  }

  private _sourceName(id: string): string {
    const src = this._heatSources.find((s) => s.id === id);
    return src ? src.name : id;
  }

  private _componentName(comp: string): string {
    const isSv = getLang(this.hass) === "sv";
    const names: Record<string, string> = {
      electric_heater: isSv ? "Elpatron" : "Direct electric heating",
      heat_pump: isSv ? "Elkompressor" : "Electric compressor",
      solar: isSv ? "Solenergi" : "Solar energy",
    };
    return names[comp] || comp;
  }
}
