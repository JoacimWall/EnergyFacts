import { LitElement, html, TemplateResult, nothing } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import { heatStyles } from "../styles";
import type { HeatSourceConfig, HeatSourceBreakdown, HeatSourcePeriodStats } from "../types";
import { t, getLocale, monthFull, monthShort } from "../localize";

type PeriodType = "today" | "day" | "week" | "month" | "year";

const PERIOD_KEYS: { type: PeriodType; labelKey: "heat.periodToday" | "heat.periodDay" | "heat.periodWeek" | "heat.periodMonth" | "heat.periodYear" }[] = [
  { type: "today", labelKey: "heat.periodToday" },
  { type: "day", labelKey: "heat.periodDay" },
  { type: "week", labelKey: "heat.periodWeek" },
  { type: "month", labelKey: "heat.periodMonth" },
  { type: "year", labelKey: "heat.periodYear" },
];

@customElement("heat-view")
export class HeatView extends LitElement {
  @property({ attribute: false }) hass: any;
  @property() entryId = "";

  @state() private _period: PeriodType = "week";
  @state() private _currentDate: Date = new Date();
  @state() private _data: HeatSourceBreakdown | null = null;
  @state() private _sources: HeatSourceConfig[] = [];
  @state() private _loading = false;
  @state() private _initialLoaded = false;
  @state() private _error = "";

  // Config form state
  @state() private _showForm = false;
  @state() private _editId = "";
  @state() private _formName = "";
  @state() private _formEnergySensor = "";
  @state() private _formMode: "standard" | "compressor" | "solar" = "standard";
  @state() private _formThreshold = 700;
  @state() private _formSolarSensor = "";
  @state() private _saving = false;
  @state() private _successMessage = "";

  static styles = [heatStyles];

  updated(changed: Map<string, unknown>) {
    if (changed.has("hass") && this.hass && this.entryId && !this._initialLoaded && !this._loading) {
      this._fetchSources();
      this._fetchData();
    }
  }

  private _getDateRange(): { start: string; end: string } {
    const d = new Date(this._currentDate);
    let start: Date;
    let end: Date;

    switch (this._period) {
      case "today": {
        const today = new Date();
        start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
        end = new Date(start);
        end.setDate(end.getDate() + 1);
        break;
      }
      case "day": {
        start = new Date(d.getFullYear(), d.getMonth(), d.getDate());
        end = new Date(start);
        end.setDate(end.getDate() + 1);
        break;
      }
      case "week": {
        const day = d.getDay();
        const diff = day === 0 ? 6 : day - 1;
        start = new Date(d.getFullYear(), d.getMonth(), d.getDate() - diff);
        end = new Date(start);
        end.setDate(end.getDate() + 7);
        break;
      }
      case "month": {
        start = new Date(d.getFullYear(), d.getMonth(), 1);
        end = new Date(d.getFullYear(), d.getMonth() + 1, 1);
        break;
      }
      case "year": {
        start = new Date(d.getFullYear(), 0, 1);
        end = new Date(d.getFullYear() + 1, 0, 1);
        break;
      }
    }

    return {
      start: this._toLocalIso(start!),
      end: this._toLocalIso(end!),
    };
  }

  private _toLocalIso(d: Date): string {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}T00:00:00`;
  }

  private _getPeriodLabel(): string {
    const d = new Date(this._currentDate);
    switch (this._period) {
      case "today":
        return t(this.hass, "heat.todayLabel");
      case "day": {
        const dd = String(d.getDate()).padStart(2, "0");
        const mon = monthShort(this.hass, d.getMonth());
        return `${dd}/${mon} ${d.getFullYear()}`;
      }
      case "week": {
        const day = d.getDay();
        const diff = day === 0 ? 6 : day - 1;
        const mon = new Date(d.getFullYear(), d.getMonth(), d.getDate() - diff);
        const sun = new Date(mon);
        sun.setDate(sun.getDate() + 6);
        const monStr = `${String(mon.getDate()).padStart(2, "0")}/${monthShort(this.hass, mon.getMonth())}`;
        const sunStr = `${String(sun.getDate()).padStart(2, "0")}/${monthShort(this.hass, sun.getMonth())}`;
        return `${monStr}-${sunStr}`;
      }
      case "month":
        return `${monthFull(this.hass, d.getMonth())} ${d.getFullYear()}`;
      case "year":
        return `${d.getFullYear()}`;
    }
  }

  private _navigate(direction: number) {
    const d = new Date(this._currentDate);
    switch (this._period) {
      case "day":
        d.setDate(d.getDate() + direction);
        break;
      case "week":
        d.setDate(d.getDate() + 7 * direction);
        break;
      case "month":
        d.setMonth(d.getMonth() + direction);
        break;
      case "year":
        d.setFullYear(d.getFullYear() + direction);
        break;
    }
    this._currentDate = d;
    this._fetchData();
  }

  private _setPeriod(p: PeriodType) {
    this._period = p;
    this._currentDate = new Date();
    this._fetchData();
  }

  private async _fetchSources() {
    if (!this.hass || !this.entryId) return;
    try {
      const result = await this.hass.callWS({
        type: "my_solar_cells/get_heat_sources",
        entry_id: this.entryId,
      });
      this._sources = result.heat_sources || [];
    } catch (e: any) {
      this._error = e.message || "Failed to fetch heat sources";
    }
  }

  private async _fetchData() {
    if (!this.hass || !this.entryId) return;
    this._loading = true;
    this._error = "";
    try {
      const range = this._getDateRange();
      const result = await this.hass.callWS({
        type: "my_solar_cells/get_heat_source_breakdown",
        entry_id: this.entryId,
        start_date: range.start,
        end_date: range.end,
      });
      this._data = result;
      this._initialLoaded = true;
    } catch (e: any) {
      this._error = e.message || "Failed to fetch data";
    }
    this._loading = false;
  }

  private _fmtKwh(v: number): string {
    return Math.round(v).toLocaleString(getLocale(this.hass), { minimumFractionDigits: 0, maximumFractionDigits: 0 }) + " kWh";
  }

  private _fmtSek(v: number): string {
    return Math.round(v).toLocaleString(getLocale(this.hass), { minimumFractionDigits: 0, maximumFractionDigits: 0 }) + " SEK";
  }

  private _fmtW(v: number): string {
    return v.toLocaleString(getLocale(this.hass), { minimumFractionDigits: 0, maximumFractionDigits: 0 }) + " W";
  }

  private _fmtPct(v: number): string {
    return v.toLocaleString(getLocale(this.hass), { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + "%";
  }

  private _openAddForm() {
    this._editId = "";
    this._formName = "";
    this._formEnergySensor = "";
    this._formMode = "standard";
    this._formThreshold = 700;
    this._formSolarSensor = "";
    this._showForm = true;
  }

  private _openEditForm(src: HeatSourceConfig) {
    this._editId = src.id;
    this._formName = src.name;
    this._formEnergySensor = src.energy_sensor;
    try {
      const cfg = JSON.parse(src.config || "{}");
      if (cfg.has_solar) {
        this._formMode = "solar";
        this._formSolarSensor = cfg.solar_sensor || "";
      } else if (cfg.has_compressor !== false) {
        this._formMode = "compressor";
        this._formSolarSensor = "";
      } else {
        this._formMode = "standard";
        this._formSolarSensor = "";
      }
      this._formThreshold = cfg.electric_heater_threshold_w || 700;
    } catch {
      this._formMode = "standard";
      this._formThreshold = 700;
      this._formSolarSensor = "";
    }
    this._showForm = true;
  }

  private _cancelForm() {
    this._showForm = false;
  }

  private async _saveSource() {
    if (!this.hass || !this.entryId || !this._formName) return;
    this._saving = true;
    const id = this._editId || this._formName.toLowerCase().replace(/[^a-z0-9]/g, "_");

    let components: { id: string; name: string }[];
    let configObj: Record<string, unknown>;

    if (this._formMode === "solar") {
      components = [{ id: "electric_heater", name: "Electricity use" }];
      configObj = {
        has_compressor: false,
        has_solar: true,
        solar_sensor: this._formSolarSensor,
        components,
        electric_heater_threshold_w: 0,
      };
    } else if (this._formMode === "compressor") {
      components = [
        { id: "heat_pump", name: "Kompressorvärme" },
        { id: "electric_heater", name: "Immersion heater" },
      ];
      configObj = {
        has_compressor: true,
        has_solar: false,
        components,
        electric_heater_threshold_w: this._formThreshold,
      };
    } else {
      components = [{ id: "electric_heater", name: "Electricity use" }];
      configObj = {
        has_compressor: false,
        has_solar: false,
        components,
        electric_heater_threshold_w: 0,
      };
    }
    const config = JSON.stringify(configObj);
    try {
      await this.hass.callWS({
        type: "my_solar_cells/save_heat_source",
        entry_id: this.entryId,
        heat_source_id: id,
        name: this._formName,
        energy_sensor: this._formEnergySensor,
        config: config,
      });
      this._showForm = false;
      this._successMessage = t(this.hass, "heat.saveSuccess");
      setTimeout(() => { this._successMessage = ""; }, 15000);
      await this._fetchSources();
      await this._fetchData();
    } catch (e: any) {
      this._error = e.message || "Save failed";
    }
    this._saving = false;
  }

  private async _rebackfillSource(src: HeatSourceConfig) {
    if (!confirm(t(this.hass, "heat.rebackfillConfirm", src.name))) return;
    try {
      await this.hass.callWS({
        type: "my_solar_cells/rebackfill_heat_source",
        entry_id: this.entryId,
        heat_source_id: src.id,
      });
      this._successMessage = t(this.hass, "heat.rebackfillSuccess");
      setTimeout(() => { this._successMessage = ""; }, 15000);
      await this._fetchData();
    } catch (e: any) {
      this._error = e.message || "Re-import failed";
    }
  }

  private async _deleteSource(src: HeatSourceConfig) {
    if (!confirm(t(this.hass, "heat.deleteConfirm", src.name))) return;
    try {
      await this.hass.callWS({
        type: "my_solar_cells/delete_heat_source",
        entry_id: this.entryId,
        heat_source_id: src.id,
      });
      await this._fetchSources();
      await this._fetchData();
    } catch (e: any) {
      this._error = e.message || "Delete failed";
    }
  }

  render(): TemplateResult {
    if (this._loading && !this._initialLoaded) {
      return html`<div class="loading">${t(this.hass, "common.loading")}</div>`;
    }
    if (this._error && !this._data) {
      return html`<div class="no-data">${t(this.hass, "common.error")}: ${this._error}</div>`;
    }

    return html`
      ${this._successMessage ? html`<div class="success-message">${this._successMessage}</div>` : nothing}
      ${this._renderPeriodNav()}
      ${this._renderBreakdown()}
      ${this._renderConfig()}
    `;
  }

  private _renderPeriodNav(): TemplateResult {
    const showArrows = this._period !== "today";
    return html`
      <div class="period-nav">
        <div class="period-tabs">
          ${PERIOD_KEYS.map(
            (pk) => html`
              <button
                class="period-tab ${this._period === pk.type ? "active" : ""}"
                @click=${() => this._setPeriod(pk.type)}
              >
                ${t(this.hass, pk.labelKey)}
              </button>
            `
          )}
        </div>
        ${showArrows
          ? html`
              <button class="nav-arrow" @click=${() => this._navigate(-1)}>&larr;</button>
              <span class="period-label">${this._getPeriodLabel()}</span>
              <button class="nav-arrow" @click=${() => this._navigate(1)}>&rarr;</button>
            `
          : nothing}
      </div>
    `;
  }

  private _renderBreakdown(): TemplateResult {
    const d = this._data;
    if (!d || d.heat_sources.length === 0) {
      return html`<div class="no-data">${this._sources.length === 0
        ? t(this.hass, "heat.noSources")
        : t(this.hass, "heat.noData")}</div>`;
    }

    return html`
      <div class="heat-sources-grid">
        ${d.heat_sources.map((s) => this._renderSourceCard(s))}
      </div>
      ${d.heat_sources.length > 1 ? html`
        <div class="heat-card">
          <h3>${t(this.hass, "heat.title")}</h3>
          <div class="heat-row heat-summary">
            <span class="label">${t(this.hass, "heat.totalEnergy")}</span>
            <span class="value">${this._fmtKwh(d.total_energy_kwh)}</span>
          </div>
          <div class="heat-row heat-summary">
            <span class="label">${t(this.hass, "heat.totalCost")}</span>
            <span class="value">${this._fmtSek(d.total_cost_sek)}</span>
          </div>
        </div>
      ` : nothing}
    `;
  }

  private _renderSourceCard(s: HeatSourcePeriodStats): TemplateResult {
    const src = this._sources.find((x) => x.id === s.heat_source_id);
    return html`
      <div class="heat-card">
        <div class="source-header">
          <h3>${s.heat_source_name}</h3>
        </div>
        ${src?.energy_state != null ? html`
          <div class="sensor-status">
            ${t(this.hass, "heat.energyValue", Math.round(Number(src.energy_state)))}
          </div>
        ` : nothing}
        ${s.has_solar ? html`
          <div class="heat-row">
            <span class="label">${t(this.hass, "heat.solarKwh")}</span>
            <span class="value">${this._fmtKwh(s.solar_energy_kwh ?? 0)}</span>
          </div>
          <div class="heat-row">
            <span class="label">${t(this.hass, "heat.solarValue")}</span>
            <span class="value">${this._fmtSek(s.solar_value_sek ?? 0)}</span>
          </div>
          <div class="heat-row">
            <span class="label">${t(this.hass, "heat.purchasedKwh")}</span>
            <span class="value">${this._fmtKwh(s.purchased_kwh ?? 0)}</span>
          </div>
          <div class="heat-row">
            <span class="label">${t(this.hass, "heat.purchasedCost")}</span>
            <span class="value">${this._fmtSek(s.purchased_cost_sek ?? 0)}</span>
          </div>
        ` : html`
          ${s.total_energy_kwh > 0 ? html`
            <div class="component-bar">
              ${s.components.map(
                (c) => html`<div class="component-bar-segment" style="width: ${c.percentage_of_total}%"></div>`
              )}
            </div>
          ` : nothing}
          ${s.components.map(
            (c) => html`
              <div class="heat-row">
                <span class="label">${c.component_name}</span>
                <span class="value">${this._fmtKwh(c.energy_kwh)} (${this._fmtPct(c.percentage_of_total)})</span>
              </div>
              <div class="heat-row">
                <span class="label">&nbsp;&nbsp;${t(this.hass, "heat.cost")}</span>
                <span class="value">${this._fmtSek(c.cost_sek)}</span>
              </div>
              <div class="heat-row">
                <span class="label">&nbsp;&nbsp;${t(this.hass, "heat.avgPower")}</span>
                <span class="value">${this._fmtW(c.avg_power_w)}</span>
              </div>
            `
          )}
        `}
        <hr class="heat-separator" />
        <div class="heat-row heat-summary">
          <span class="label">${t(this.hass, "heat.totalEnergy")}</span>
          <span class="value">${this._fmtKwh(s.total_energy_kwh)}</span>
        </div>
        <div class="heat-row heat-summary">
          <span class="label">${t(this.hass, "heat.totalCost")}</span>
          <span class="value">${this._fmtSek(s.total_cost_sek)}</span>
        </div>
      </div>
    `;
  }

  private _renderConfig(): TemplateResult {
    return html`
      <div class="config-section">
        <div class="heat-card">
          <h3>${t(this.hass, "heat.configTitle")}</h3>
          ${this._sources.map(
            (src) => html`
              <div class="heat-row">
                <span class="label">${src.name} (${src.energy_sensor})</span>
                <span class="source-actions">
                  <button @click=${() => this._openEditForm(src)}>${t(this.hass, "heat.editSource")}</button>
                  <button @click=${() => this._rebackfillSource(src)}>${t(this.hass, "heat.rebackfill")}</button>
                  <button @click=${() => this._deleteSource(src)}>${t(this.hass, "common.delete")}</button>
                </span>
              </div>
            `
          )}
          ${!this._showForm
            ? html`<button class="heat-btn" @click=${this._openAddForm}>${t(this.hass, "heat.addSource")}</button>`
            : this._renderForm()}
        </div>
      </div>
    `;
  }

  private _renderForm(): TemplateResult {
    const modes: Array<{ value: "standard" | "compressor" | "solar"; key: "heat.modeStandard" | "heat.modeCompressor" | "heat.modeSolar" }> = [
      { value: "standard", key: "heat.modeStandard" },
      { value: "compressor", key: "heat.modeCompressor" },
      { value: "solar", key: "heat.modeSolar" },
    ];
    return html`
      <div class="config-form">
        <div class="input-group">
          <label>${t(this.hass, "heat.sourceName")}</label>
          <input
            type="text"
            .value=${this._formName}
            @input=${(e: Event) => { this._formName = (e.target as HTMLInputElement).value; }}
          />
        </div>
        <div class="input-group">
          ${modes.map((m) => html`
            <label style="display:block;margin-bottom:4px">
              <input
                type="radio"
                name="heat-mode"
                .value=${m.value}
                .checked=${this._formMode === m.value}
                @change=${() => { this._formMode = m.value; }}
              />
              ${t(this.hass, m.key)}
            </label>
          `)}
        </div>
        ${this._formMode === "compressor" ? html`
          <div class="input-group">
            <label>${t(this.hass, "heat.threshold")} (${t(this.hass, "heat.thresholdUnit")})</label>
            <input
              type="number"
              .value=${String(this._formThreshold)}
              @input=${(e: Event) => { this._formThreshold = parseInt((e.target as HTMLInputElement).value) || 700; }}
            />
          </div>
        ` : nothing}
        ${this._formMode === "solar" ? html`
          <div class="input-group">
            <label>${t(this.hass, "heat.solarSensor")}</label>
            <input
              type="text"
              .value=${this._formSolarSensor}
              @input=${(e: Event) => { this._formSolarSensor = (e.target as HTMLInputElement).value; }}
            />
          </div>
        ` : nothing}
        <div class="input-group">
          <label>${t(this.hass, "heat.energySensor")}</label>
          <input
            type="text"
            .value=${this._formEnergySensor}
            @input=${(e: Event) => { this._formEnergySensor = (e.target as HTMLInputElement).value; }}
          />
        </div>
      </div>
      <button class="heat-btn" @click=${this._saveSource} ?disabled=${this._saving}>
        ${this._saving ? t(this.hass, "common.loading") : t(this.hass, "common.save")}
      </button>
      <button class="heat-btn" @click=${this._cancelForm}>${t(this.hass, "common.cancel")}</button>
    `;
  }
}
