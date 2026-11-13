/**
 * Graphiques ECharts GÉNÉRIQUES (line / scatter / treemap)
 * Complément de dashboard.js — appelé à l'exécution par Dashboard.buildEChartsOption().
 * Conservé pour compatibilité ; l'agent.js n'en dépend pas directement.
 */
window.DashboardCharts = (function () {
  const PALETTE = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#f97316', '#ec4899'];
  const isTimeKey = k => /^(year|annee|date|month|mois|period|quarter)/i.test(k);
  const compact = v => { const a = Math.abs(v); return a >= 1e12 ? (v / 1e12).toFixed(1) + 'T' : a >= 1e9 ? (v / 1e9).toFixed(1) + 'B' : a >= 1e6 ? (v / 1e6).toFixed(1) + 'M' : v; };
  const fmt = (v, meta) => (window.Dashboard && window.Dashboard.formatValue) ? window.Dashboard.formatValue(v, meta.valueFormat || 'auto') : v;
  const axisTxt = { color: '#9ca3af', fontSize: 11 };
  const split = { lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } };

  function labelKey(data, meta) {
    if (meta.labelField && data[0] && data[0][meta.labelField] !== undefined) return meta.labelField;
    const keys = Object.keys(data[0] || {});
    return keys.find(isTimeKey) || keys.find(k => typeof data[0][k] === 'string') || keys[0];
  }
  function seriesDefs(data, meta, lk) {
    if (Array.isArray(meta.series) && meta.series.length) return meta.series;
    return Object.keys(data[0] || {}).filter(k => k !== lk && typeof data[0][k] === 'number').map(k => ({ name: k, field: k }));
  }

  function line(data, meta, tip) {
    const lk = labelKey(data, meta), defs = seriesDefs(data, meta, lk);
    return {
      tooltip: Object.assign({}, tip, { trigger: 'axis', formatter: ps => `<b>${ps[0].name}</b><br/>` + ps.map(p => `${p.marker} ${p.seriesName}: <b>${fmt(p.value, meta)}</b>`).join('<br/>') }),
      legend: defs.length > 1 ? { data: defs.map(d => d.name), textStyle: axisTxt, top: 0 } : undefined,
      grid: { left: '3%', right: '4%', bottom: '5%', top: defs.length > 1 ? '15%' : '10%', containLabel: true },
      xAxis: { type: 'category', data: data.map(d => String(d[lk])), axisLine: { lineStyle: { color: '#374151' } }, axisLabel: axisTxt },
      yAxis: { type: 'value', splitLine: split, axisLabel: Object.assign({}, axisTxt, { formatter: compact }), min: meta.yAxisMin != null ? meta.yAxisMin : undefined, max: meta.yAxisMax != null ? meta.yAxisMax : undefined, interval: meta.yAxisInterval != null ? meta.yAxisInterval : undefined },
      series: defs.map((d, i) => {
        const col = i === 0 ? (meta.lineColor || PALETTE[0]) : PALETTE[i % PALETTE.length];
        return {
          name: d.name, type: 'line', smooth: true, data: data.map(r => r[d.field]),
          lineStyle: { width: i === 0 ? 3 : 2, color: col }, itemStyle: { color: col },
          label: { show: meta.showDataLabels === true, position: 'top', color: '#e2e8f0', fontSize: 11, formatter: p => compact(p.value) },
          areaStyle: i === 0 ? { color: col, opacity: 0.18 } : undefined
        };
      })
    };
  }

  function scatter(data, meta, tip) {
    const lk = labelKey(data, meta), nums = Object.keys(data[0] || {}).filter(k => typeof data[0][k] === 'number');
    const xf = meta.xField || nums[0], yf = meta.yField || nums[1] || nums[0];
    const xn = meta.xName || xf, yn = meta.yName || yf;
    return {
      tooltip: Object.assign({}, tip, { formatter: p => `<b>${p.value[2]}</b><br/>${xn}: <b>${compact(p.value[0])}</b><br/>${yn}: <b>${compact(p.value[1])}</b>` }),
      grid: { left: '3%', right: '5%', bottom: '10%', top: '12%', containLabel: true },
      xAxis: { name: xn, nameLocation: 'middle', nameGap: 28, nameTextStyle: axisTxt, splitLine: split, axisLabel: Object.assign({}, axisTxt, { formatter: compact }) },
      yAxis: { name: yn, nameTextStyle: axisTxt, splitLine: split, axisLabel: Object.assign({}, axisTxt, { formatter: compact }) },
      series: [{
        type: 'scatter', symbolSize: 14, data: data.map(d => [d[xf], d[yf], String(d[lk])]),
        itemStyle: { color: meta.scatterColor || '#8b5cf6', shadowBlur: 10, shadowColor: 'rgba(139, 92, 246, 0.5)' }
      }]
    };
  }

  function treemap(data, meta, tip) {
    const lk = labelKey(data, meta), defs = seriesDefs(data, meta, lk), vf = meta.valueField || (defs[0] && defs[0].field);
    return {
      tooltip: Object.assign({}, tip, { formatter: p => `<b>${p.name}</b><br/>${meta.metricLabel || 'Valeur'}: <b>${fmt(p.value, meta)}</b>` }),
      series: [{
        type: 'treemap', roam: false, nodeClick: false, breadcrumb: { show: false },
        label: { show: true, formatter: p => p.name, color: '#fff', fontSize: 12 },
        itemStyle: { borderColor: '#111827', borderWidth: 2, gapWidth: 2 },
        data: data.map(d => ({ name: String(d[lk]), value: Math.abs(Number(d[vf])) || 0 }))
      }]
    };
  }

  return { build: (type, data, meta, tip) => ({ line, echarts_line: line, scatter, treemap }[type] || (() => ({})))(data || [], meta || {}, tip || {}), line, scatter, treemap };
})();


/**
 * BI Dashboard Engine — Version compatible BIAgent v5.1
 * Powered by Apache ECharts.
 *
 *  CHANGEMENTS v2 (compat agent v5.1) :
 *   1. addVisual() retourne TOUJOURS un id, ou LÈVE une erreur explicite.
 *   2. updateVisual(cardId, cfgOrMeta, style) accepte un cfg COMPLET :
 *      si l'objet contient `data`/`series`/`chartType`/`labelField`, on REMPLACE
 *      reg.config (au lieu de fusionner dans reg.meta) → re-render complet.
 *   3. changeChartType() renvoie `true` même si l'instance ECharts n'est pas
 *      encore prête (re-render différé au prochain tick).
 *   4. getActiveOrLatestCardId() protégé contre un registre vide.
 *   5. seedDefaultCharts() marque les visuels par défaut SANS `_agentSid`
 *      → restore() de l'agent peut les supprimer sans ambiguïté.
 *   6. window.__DASHBOARD_READY__ exposé après init().
 */
window.Dashboard = (function () {
  const chartInstances = {};
  const visualRegistry = {};
  let visualCounter = 0;
  let activeCardId = null;

  // ── Helpers de formatage ──
  function formatMoney(num) {
    if (num === null || num === undefined) return '$0';
    if (Math.abs(num) >= 1e12) return '$' + (num / 1e12).toFixed(2) + ' T';
    if (Math.abs(num) >= 1e9) return '$' + (num / 1e9).toFixed(2) + ' B';
    if (Math.abs(num) >= 1e6) return '$' + (num / 1e6).toFixed(2) + ' M';
    return '$' + Number(num).toLocaleString();
  }
  function formatNumber(num) {
    if (num === null || num === undefined) return '0';
    return Number(num).toLocaleString();
  }
  function formatCompact(val, isPercent) {
    if (val === null || val === undefined || isNaN(val)) return '-';
    const num = Number(val);
    if (isPercent) return num.toFixed(2) + '%';
    const abs = Math.abs(num);
    if (abs >= 1e12) return (num / 1e12).toFixed(1) + 'T';
    if (abs >= 1e9) return (num / 1e9).toFixed(1) + 'B';
    if (abs >= 1e6) return (num / 1e6).toFixed(1) + 'M';
    if (abs >= 1e3) return (num / 1e3).toFixed(1) + 'K';
    if (Number.isInteger(num)) return String(num);
    return num.toFixed(2);
  }
  function formatValue(v, kind) {
    if (v === null || v === undefined) return '–';
    if (kind === 'money') return formatMoney(v);
    if (kind === 'percent') return (Number(v) * (Math.abs(v) <= 1 ? 100 : 1)).toFixed(1) + '%';
    if (kind === 'count') return formatNumber(v);
    return typeof v === 'number' ? formatNumber(v) : String(v);
  }
  function adjustBrightness(col, percent) {
    if (!col || !col.startsWith('#')) return '#1e40af';
    let num = parseInt(col.slice(1), 16);
    let r = (num >> 16) + percent;
    let b = ((num >> 8) & 0x00FF) + percent;
    let g = (num & 0x0000FF) + percent;
    r = Math.max(Math.min(255, r), 0);
    b = Math.max(Math.min(255, b), 0);
    g = Math.max(Math.min(255, g), 0);
    return '#' + (g | (b << 8) | (r << 16)).toString(16).padStart(6, '0');
  }

  // ── KPI summary cards (haut de page) ──
  function initSummaryCards(customCatalog) {
    const container = document.getElementById('kpi-summary-container');
    if (!container) return;

    const catalog = customCatalog || window.KPIS_CATALOG;
    const colors = ['blue', 'purple', 'emerald', 'amber', 'cyan'];
    const icons = ['↗', '⚡', '✦', '●', '★'];

    // 1. Essai de charger les KPI Cards depuis kpis_catalog.json
    if (catalog && Array.isArray(catalog.kpis)) {
      const cardKpis = catalog.kpis.filter(k =>
        k.active !== false && (
          k.chart_type === 'card' ||
          k.superset_chart_type === 'big_number_total' ||
          k.current_value_formatted ||
          (typeof k.raw_value === 'number')
        )
      );

      if (cardKpis.length >= 1) {
                container.innerHTML = cardKpis.slice(0, 6).map((k, idx) => {
          const col = colors[idx % colors.length];
          const ico = icons[idx % icons.length];
          const val = k.formatted_value || k.current_value_formatted || (k.raw_value != null ? formatMoney(k.raw_value) : '-');
          const variancePill = k.variance_label
            ? `<div class="kpi-variance ${k.status === 'below_target' ? 'negative' : (k.status === 'optimal' ? 'neutral' : 'positive')}">${escapeHtml(k.variance_label)}</div>`
            : '';
          const sub = k.target_formatted ? `Seuil Métier : ${escapeHtml(k.target_formatted)}` : (k.domain || k.source_table || 'Métrique certifiée');
          return `
            <div class="kpi-card ${col}">
              <div class="kpi-label">${escapeHtml(k.name)}</div>
              <div class="kpi-value">${escapeHtml(String(val))}</div>
              ${variancePill}
              <div class="kpi-subtext"><span>${ico}</span> ${escapeHtml(String(sub))}</div>
            </div>
          `;
        }).join('');
        return;
      }
    }

    // 2. Si aucun dataset actif : cartes d'attente dynamiques
    container.innerHTML = `
      <div class="kpi-card blue" style="opacity: 0.85;">
        <div class="kpi-label">Dataset Actif</div>
        <div class="kpi-value" style="font-size: 20px;">En attente</div>
        <div class="kpi-subtext"><span>📂</span> Parcourez un fichier Excel / CSV</div>
      </div>
      <div class="kpi-card purple" style="opacity: 0.85;">
        <div class="kpi-label">Volume de Données</div>
        <div class="kpi-value" style="font-size: 20px;">0 ligne</div>
        <div class="kpi-subtext"><span>⚡</span> Détection automatique</div>
      </div>
      <div class="kpi-card emerald" style="opacity: 0.85;">
        <div class="kpi-label">Catalogue KPIs</div>
        <div class="kpi-value" style="font-size: 20px;">0 KPI</div>
        <div class="kpi-subtext"><span>✦</span> kpis_catalog.json</div>
      </div>
      <div class="kpi-card amber" style="opacity: 0.85;">
        <div class="kpi-label">Moteur SQL</div>
        <div class="kpi-value" style="font-size: 20px;">Apache Superset</div>
        <div class="kpi-subtext"><span>●</span> Agrégations automatiques</div>
      </div>
      <div class="kpi-card cyan" style="opacity: 0.85;">
        <div class="kpi-label">IA Copilot</div>
        <div class="kpi-value" style="font-size: 20px;">Prêt</div>
        <div class="kpi-subtext"><span>★</span> Requetage par prompt</div>
      </div>
    `;
  }

  // ── Construction des options ECharts ──
  function buildEChartsOption(type, data, meta) {
    meta = meta || {};
    if (!Array.isArray(data)) data = [];

    const baseTooltip = {
      backgroundColor: 'rgba(17, 24, 39, 0.95)',
      borderColor: 'rgba(255, 255, 255, 0.15)',
      textStyle: { color: '#f3f4f6', fontSize: 12 },
      extraCssText: 'box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5); border-radius: 8px;'
    };

    const palette = (Array.isArray(meta.palette) && meta.palette.length)
      ? meta.palette
      : [
        meta.barColor || '#3b82f6',
        '#10b981', '#f59e0b', '#ec4899', '#8b5cf6', '#06b6d4', '#6366f1'
      ];

    // ── 1. BAR ──
    if (type === 'bar' || type === 'echarts_bar') {
      const labelKey = meta.labelField || (data[0] ? Object.keys(data[0]).find(k => ['country', 'sector', 'name', 'category', 'year', 'dim', 'label'].includes(k)) : null);
      const categories = data.map(d => {
        if (labelKey && d[labelKey] !== undefined) return String(d[labelKey]);
        return String(d.name || d.country || d.sector || d.category || d.year || Object.values(d)[0] || '');
      });

      let seriesList = [];
      const hasMultipleSeries = Array.isArray(meta.series) && meta.series.length > 1;

      if (hasMultipleSeries) {
        seriesList = meta.series.map((s, idx) => {
          const fieldName = s.field || s.name;
          const isPercentOrRatio = /%|croissance|growth|taux|rate|ratio|margin|roe|pe_ratio/i.test((s.name || '') + ' ' + (fieldName || ''));
          const sColor = palette[idx % palette.length];
          const seriesType = (idx >= 1 && isPercentOrRatio) ? 'line' : 'bar';
          const yAxisIdx = (idx === 1 && isPercentOrRatio) ? 1 : 0;
          return {
            name: s.name || fieldName,
            type: seriesType,
            yAxisIndex: yAxisIdx,
            smooth: true,
            data: data.map(d => {
              const v = d[fieldName] !== undefined ? d[fieldName] : (d.value !== undefined ? d.value : 0);
              return typeof v === 'number' ? v : (parseFloat(v) || 0);
            }),
            itemStyle: {
              color: seriesType === 'bar' ? new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: sColor },
                { offset: 1, color: adjustBrightness(sColor, -30) }
              ]) : sColor,
              borderRadius: seriesType === 'bar' ? (meta.horizontal ? [0, 6, 6, 0] : [6, 6, 0, 0]) : 0
            },
            lineStyle: seriesType === 'line' ? { width: 3, color: sColor } : undefined,
            label: {
              show: meta.showDataLabels === true,
              position: seriesType === 'line' ? 'top' : (meta.horizontal ? 'right' : 'top'),
              color: '#e2e8f0', fontSize: 10,
              formatter: p => formatCompact(p.value, isPercentOrRatio)
            }
          };
        });
      } else {
        const valueKey = meta.valueField || (data[0] ? Object.keys(data[0]).find(k => k !== labelKey && typeof data[0][k] === 'number') : null);
        const values = data.map((d, idx) => {
          let num = 0;
          if (valueKey && d[valueKey] !== undefined) num = Number(d[valueKey]) || 0;
          else if (d.value !== undefined) num = Number(d.value) || 0;
          else {
            for (const k of Object.keys(d)) {
              if (k !== labelKey && typeof d[k] === 'number') { num = d[k]; break; }
            }
          }
          const catName = String((labelKey && d[labelKey]) || d.comparison || d.name || d.category || d.sector || d.country || '');
          let catColor = null;
          if (meta.categoryColors) {
            const matchKey = Object.keys(meta.categoryColors).find(k => k.trim().toLowerCase() === catName.trim().toLowerCase());
            if (matchKey) catColor = meta.categoryColors[matchKey];
          }
          if (!catColor && meta.colors && meta.colors[idx]) {
            catColor = meta.colors[idx];
          }
          if (catColor) {
            const barItemColor = (typeof catColor === 'string' && (catColor.startsWith('#') || catColor.startsWith('rgb')))
              ? new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: catColor },
                { offset: 1, color: adjustBrightness(catColor, -30) }
              ])
              : catColor;
            return {
              value: num,
              itemStyle: { color: barItemColor, borderRadius: meta.horizontal ? [0, 6, 6, 0] : [6, 6, 0, 0] }
            };
          }
          return num;
        });

        const barColor = meta.barColor || palette[0];
        const itemStyleColor = (typeof barColor === 'string' && (barColor.startsWith('#') || barColor.startsWith('rgb')))
          ? new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: barColor },
            { offset: 1, color: adjustBrightness(barColor, -30) }
          ])
          : barColor;

        seriesList = [{
          name: meta.metricLabel || meta.title || 'Métrique',
          type: 'bar',
          data: values,
          itemStyle: { borderRadius: meta.horizontal ? [0, 6, 6, 0] : [6, 6, 0, 0], color: itemStyleColor },
          label: {
            show: meta.showDataLabels === true,
            position: meta.horizontal
              ? (meta.labelPosition === 'inside' ? 'insideRight' : 'right')
              : (meta.labelPosition === 'inside' ? 'inside' : 'top'),
            color: '#e2e8f0', fontSize: 11,
            formatter: p => formatCompact(p.value, meta.valueFormat === 'percent')
          }
        }];
      }

      const hasDualAxis = seriesList.some(s => s.yAxisIndex === 1);
      const isHorizontal = meta.horizontal === true;

      const primaryValueAxis = {
        type: 'value',
        name: hasDualAxis ? seriesList[0].name.slice(0, 15) : undefined,
        nameTextStyle: { color: '#9ca3af', fontSize: 10 },
        splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } },
        axisLabel: { color: '#9ca3af', formatter: val => formatCompact(val, meta.valueFormat === 'percent') }
      };
      if (meta.yAxisMin !== undefined && meta.yAxisMin !== null) primaryValueAxis.min = Number(meta.yAxisMin);
      if (meta.yAxisMax !== undefined && meta.yAxisMax !== null) primaryValueAxis.max = Number(meta.yAxisMax);
      if (meta.yAxisInterval !== undefined && meta.yAxisInterval !== null) primaryValueAxis.interval = Number(meta.yAxisInterval);

      let yAxisConfig, xAxisConfig;
      if (isHorizontal) {
        xAxisConfig = primaryValueAxis;
        yAxisConfig = { type: 'category', data: categories, axisLine: { lineStyle: { color: '#374151' } }, axisLabel: { color: '#9ca3af', fontSize: 11 } };
      } else {
        xAxisConfig = {
          type: 'category', data: categories,
          axisLine: { lineStyle: { color: '#374151' } },
          axisLabel: { color: '#9ca3af', fontSize: 11, rotate: categories.length > 5 ? 28 : 0, interval: 0 }
        };
        if (hasDualAxis) {
          const secondaryValueAxis = {
            type: 'value',
            name: seriesList.find(s => s.yAxisIndex === 1)?.name.slice(0, 15),
            nameTextStyle: { color: '#9ca3af', fontSize: 10 },
            splitLine: { show: false },
            axisLabel: { color: '#9ca3af', formatter: val => formatCompact(val, true) }
          };
          yAxisConfig = [primaryValueAxis, secondaryValueAxis];
        } else {
          yAxisConfig = primaryValueAxis;
        }
      }

      return {
        tooltip: Object.assign({}, baseTooltip, {
          trigger: 'axis', axisPointer: { type: 'shadow' },
          formatter: function (params) {
            if (!Array.isArray(params)) params = [params];
            let res = `<b>${params[0].name}</b><br/>`;
            params.forEach(p => {
              const isPct = /%|croissance|growth|taux|rate/i.test(p.seriesName);
              res += `${p.marker} ${p.seriesName}: <b>${formatCompact(p.value, isPct)}</b><br/>`;
            });
            return res;
          }
        }),
        legend: (hasMultipleSeries || seriesList.length > 1) ? {
          show: true, data: seriesList.map(s => s.name),
          textStyle: { color: '#9ca3af', fontSize: 11 }, top: 0
        } : undefined,
        grid: {
          left: '3%', right: hasDualAxis ? '6%' : '4%', bottom: '10%',
          top: (hasMultipleSeries || meta.showDataLabels) ? '18%' : '12%',
          containLabel: true
        },
        xAxis: xAxisConfig,
        yAxis: yAxisConfig,
        series: seriesList
      };
    }

    // ── 2. PIE / DONUT ──
    if (type === 'pie' || type === 'donut') {
      const isOutside = meta.labelPosition === 'outside' || meta.showOutsideLabels === true;
      const isNone = meta.labelPosition === 'none';

      let labelFormat = '{b}\n{c} ({d}%)';
      if (meta.labelFormat === 'percent_only') labelFormat = '{b}: {d}%';
      if (meta.labelFormat === 'value_only') labelFormat = '{b}: {c}';

      const labelKey = meta.labelField || (data[0] ? Object.keys(data[0]).find(k => ['category', 'sector', 'name', 'country', 'label'].includes(k)) : null);
      const valueKey = meta.valueField || (data[0] ? Object.keys(data[0]).find(k => k !== labelKey && typeof data[0][k] === 'number') : null);

      const pieData = data.map((d, idx) => {
        const name = String((labelKey && d[labelKey]) || d.comparison || d.category || d.sector || d.name || d.country || 'Item');
        let val = 0;
        if (valueKey && d[valueKey] !== undefined) val = d[valueKey];
        else if (d.count !== undefined) val = d.count;
        else if (d.value !== undefined) val = d.value;
        else {
          for (const k of Object.keys(d)) {
            if (k !== labelKey && typeof d[k] === 'number') { val = d[k]; break; }
          }
        }
        let sliceColor = null;
        if (meta.categoryColors) {
          const matchKey = Object.keys(meta.categoryColors).find(k => {
            const kNorm = k.trim().toLowerCase();
            const nNorm = name.trim().toLowerCase();
            return kNorm === nNorm || nNorm.includes(kNorm) || kNorm.includes(nNorm);
          });
          if (matchKey) sliceColor = meta.categoryColors[matchKey];
        }
        if (!sliceColor && meta.colors && meta.colors[idx]) sliceColor = meta.colors[idx];
        if (!sliceColor && d.color) sliceColor = d.color;
        if (!sliceColor && meta.palette && meta.palette[idx % meta.palette.length]) sliceColor = meta.palette[idx % meta.palette.length];
        if (!sliceColor && palette && palette[idx % palette.length]) sliceColor = palette[idx % palette.length];

        return {
          name: name,
          value: Number(val) || 0,
          itemStyle: {
            color: sliceColor || undefined,
            borderRadius: 6,
            borderColor: '#111827',
            borderWidth: 2
          }
        };
      });

      return {
        color: meta.colors || (meta.palette && meta.palette.length ? meta.palette : undefined) || palette,
        tooltip: Object.assign({}, baseTooltip, {
          trigger: 'item',
          formatter: function (p) {
            const valStr = typeof p.value === 'number' && p.value > 1000 ? formatMoney(p.value) : p.value;
            return `${p.name}: <b>${valStr}</b> (${p.percent}%)`;
          }
        }),
        legend: {
          orient: isOutside ? 'horizontal' : 'vertical',
          bottom: isOutside ? 0 : 'auto',
          right: isOutside ? 'auto' : 5,
          top: isOutside ? 'auto' : 'center',
          textStyle: { color: '#9ca3af', fontSize: 11 },
          formatter: name => name.length > 18 ? name.substring(0, 16) + '...' : name
        },
        series: [{
          name: meta.title || 'Catégories',
          type: 'pie',
          radius: ['40%', isOutside ? '65%' : '72%'],
          center: isOutside ? ['50%', '45%'] : ['40%', '50%'],
          avoidLabelOverlap: true,
          label: {
            show: !isNone,
            position: isOutside ? 'outside' : 'inside',
            formatter: isOutside ? labelFormat : '{d}%',
            color: isOutside ? '#f3f4f6' : '#ffffff',
            fontSize: isOutside ? 11 : 12,
            fontWeight: isOutside ? 'normal' : 'bold'
          },
          labelLine: { show: isOutside, length: 12, length2: 12, lineStyle: { color: 'rgba(255, 255, 255, 0.4)' } },
          emphasis: { label: { show: true, fontSize: 13, fontWeight: 'bold', color: '#fff' } },
          data: pieData
        }]
      };
    }

    // ── 3. LINE ──
    if (type === 'line' || type === 'echarts_line') {
      const labelKey = meta.labelField || (data[0] ? (('year' in data[0]) ? 'year' : ('date' in data[0]) ? 'date' : ('name' in data[0]) ? 'name' : Object.keys(data[0])[0]) : 'year');
      const xCategories = data.map(d => String(d[labelKey] ?? ''));

      let seriesConfig = [];
      const colors = [meta.lineColor || '#3b82f6', '#10b981', '#f59e0b', '#ec4899', '#8b5cf6'];

      if (meta.series && Array.isArray(meta.series) && meta.series.length > 0) {
        seriesConfig = meta.series.map((s, idx) => ({
          name: s.name || s.field, type: 'line', smooth: true,
          data: data.map(d => Number(d[s.field ?? s.name]) || 0),
          lineStyle: { width: 3, color: colors[idx % colors.length] },
          itemStyle: { color: colors[idx % colors.length] }
        }));
      } else {
        const valueKey = meta.valueField || (data[0] ? Object.keys(data[0]).find(k => k !== labelKey && typeof data[0][k] === 'number') : 'value');
        seriesConfig = [{
          name: meta.metricLabel || meta.title || 'Métrique', type: 'line', smooth: true,
          data: data.map(d => Number(d[valueKey]) || 0),
          lineStyle: { width: 3, color: meta.lineColor || '#3b82f6' },
          itemStyle: { color: meta.lineColor || '#3b82f6' }
        }];
      }

      return {
        tooltip: Object.assign({}, baseTooltip, {
          trigger: 'axis',
          formatter: function (params) {
            let res = `<b>${params[0].name}</b><br/>`;
            params.forEach(p => { res += `${p.marker} ${p.seriesName}: <b>${formatCompact(p.value, false)}</b><br/>`; });
            return res;
          }
        }),
        legend: { data: seriesConfig.map(s => s.name), textStyle: { color: '#9ca3af', fontSize: 11 }, top: 0 },
        grid: { left: '3%', right: '4%', bottom: '5%', top: '15%', containLabel: true },
        xAxis: { type: 'category', data: xCategories, axisLine: { lineStyle: { color: '#374151' } }, axisLabel: { color: '#9ca3af' } },
        yAxis: { type: 'value', splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.05)' } }, axisLabel: { color: '#9ca3af', formatter: val => formatCompact(val, false) } },
        series: seriesConfig
      };
    }

    // ── 4. SCATTER ──
    if (type === 'scatter') {
      const xKey = meta.xField || (data[0] ? Object.keys(data[0]).find(k => ['gdp_growth', 'growth', 'x'].includes(k)) : 'gdp_growth');
      const yKey = meta.yField || (data[0] ? Object.keys(data[0]).find(k => ['inflation', 'pe_ratio', 'y'].includes(k)) : 'inflation');
      const labelKey = meta.labelField || (data[0] ? Object.keys(data[0]).find(k => ['country', 'name', 'label'].includes(k)) : 'country');
      const xName = meta.xName || (xKey ? xKey.toUpperCase() : 'X');
      const yName = meta.yName || (yKey ? yKey.toUpperCase() : 'Y');
      return {
        tooltip: Object.assign({}, baseTooltip, {
          formatter: function (params) {
            const d = params.value;
            return `<b>${d[2]}</b><br/>${xName}: <b>${formatCompact(d[0], false)}</b><br/>${yName}: <b>${formatCompact(d[1], false)}</b>`;
          }
        }),
        grid: { left: '3%', right: '5%', bottom: '8%', top: '12%', containLabel: true },
        xAxis: { name: xName, nameLocation: 'middle', nameGap: 25, nameTextStyle: { color: '#9ca3af', fontSize: 11 }, splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.05)' } }, axisLabel: { color: '#9ca3af' } },
        yAxis: { name: yName, nameTextStyle: { color: '#9ca3af', fontSize: 11 }, splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.05)' } }, axisLabel: { color: '#9ca3af' } },
        series: [{
          type: 'scatter', symbolSize: 14,
          data: data.map((d, idx) => {
            const ptName = String(d[labelKey] ?? '');
            let ptColor = null;
            if (meta.categoryColors) {
              const matchKey = Object.keys(meta.categoryColors).find(k => k.trim().toLowerCase() === ptName.trim().toLowerCase());
              if (matchKey) ptColor = meta.categoryColors[matchKey];
            }
            if (!ptColor && meta.colors && meta.colors[idx]) ptColor = meta.colors[idx];
            if (!ptColor) ptColor = meta.scatterColor || '#8b5cf6';
            return {
              value: [Number(d[xKey] ?? 0), Number(d[yKey] ?? 0), ptName],
              itemStyle: { color: ptColor, shadowBlur: 10, shadowColor: (typeof ptColor === 'string' && ptColor.startsWith('#') ? ptColor : '#8b5cf6') + '80' }
            };
          })
        }]
      };
    }

    // ── 5. TREEMAP ──
    if (type === 'treemap') {
      const labelKey = meta.labelField || (data[0] ? Object.keys(data[0]).find(k => ['sector', 'name', 'country', 'category'].includes(k)) : null);
      const valueKey = meta.valueField || (data[0] ? Object.keys(data[0]).find(k => k !== labelKey && typeof data[0][k] === 'number') : null);
      return {
        tooltip: Object.assign({}, baseTooltip, {
          formatter: function (params) {
            return `<b>${params.name}</b><br/>${meta.metricLabel || 'Valeur'}: <b>${formatCompact(params.value, false)}</b>`;
          }
        }),
        series: [{
          type: 'treemap', roam: false, nodeClick: false, breadcrumb: { show: false },
          label: { show: true, formatter: '{b}\n{c}', color: '#fff', fontSize: 12 },
          itemStyle: { borderColor: '#111827', borderWidth: 2, gapWidth: 2 },
          data: data.map((d, idx) => {
            const itemName = String((labelKey && d[labelKey]) || d.sector || d.name || d.country || d.category || 'Item');
            let itemColor = null;
            if (meta.categoryColors) {
              const matchKey = Object.keys(meta.categoryColors).find(k => k.trim().toLowerCase() === itemName.trim().toLowerCase());
              if (matchKey) itemColor = meta.categoryColors[matchKey];
            }
            if (!itemColor && meta.colors && meta.colors[idx]) itemColor = meta.colors[idx];
            return {
              name: itemName,
              value: Number((valueKey && d[valueKey] !== undefined) ? d[valueKey] : (d.revenue || d.market_cap || d.value || d.count || 0)),
              itemStyle: itemColor ? { color: itemColor } : undefined
            };
          })
        }]
      };
    }

    return {};
  }

  // ── Gestion de l'arrière-plan du Dashboard (Global) ──
  function setDashboardBackground(color, persist) {
    if (!color) return;
    const bg = String(color).trim();
    if (typeof document !== 'undefined') {
      try {
        document.documentElement.style.setProperty('--bg-primary', bg);
        if (document.body) document.body.style.backgroundColor = bg;
        const pane = document.querySelector('.dashboard-pane');
        if (pane) {
          pane.style.backgroundColor = bg;
          pane.style.background = `radial-gradient(circle at top left, rgba(37, 99, 235, 0.05), transparent 40%), radial-gradient(circle at bottom right, rgba(139, 92, 246, 0.04), transparent 50%), ${bg}`;
        }
        const appMain = document.querySelector('.app-main') || document.querySelector('.main-wrapper');
        if (appMain) appMain.style.backgroundColor = bg;
      } catch (e) {
        console.warn('[Dashboard] setDashboardBackground error', e);
      }
    }
    try {
      localStorage.setItem('bi_dashboard_bg', bg);
    } catch (e) { }

    if (persist !== false && typeof fetch === 'function') {
      fetch('/api/agent/dashboard-bg', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ background: bg })
      }).catch(e => console.warn('[Dashboard] sync dashboard-bg failed', e));
    }
  }

  function restoreDashboardBackground() {
    try {
      const saved = localStorage.getItem('bi_dashboard_bg');
      if (saved) setDashboardBackground(saved, false);
      if (typeof fetch === 'function') {
        fetch('/api/agent/dashboard-bg')
          .then(r => (r.ok ? r.json() : null))
          .then(d => {
            if (d && d.background) setDashboardBackground(d.background, false);
          })
          .catch(() => { });
      }
    } catch (e) { }
  }
  // Restauration immédiate au chargement du script
  try { restoreDashboardBackground(); } catch (e) { }

  // ── Style du conteneur ──
  function applyContainerStyle(cardElement, style) {
    if (!cardElement) return;
    if (style.backgroundColor) {
      cardElement.style.backgroundColor = style.backgroundColor;
      cardElement.style.background = style.backgroundColor;
    }
    if (style.backdropFilter) {
      cardElement.style.backdropFilter = style.backdropFilter;
      cardElement.style.webkitBackdropFilter = style.backdropFilter;
    }
    if (style.borderRadius !== undefined) {
      cardElement.style.borderRadius = typeof style.borderRadius === 'number' ? `${style.borderRadius}px` : style.borderRadius;
    }
    if (style.boxShadow) cardElement.style.boxShadow = style.boxShadow;
    if (style.border) cardElement.style.border = style.border;
    if (style.borderWidth !== undefined) {
      const bw = typeof style.borderWidth === 'number' ? `${style.borderWidth}px` : style.borderWidth;
      cardElement.style.borderWidth = bw;
      if (!cardElement.style.borderStyle || cardElement.style.borderStyle === 'none') {
        cardElement.style.borderStyle = style.borderStyle || 'solid';
      }
      if (style.borderColor) {
        cardElement.style.borderColor = style.borderColor;
      } else if (!cardElement.style.borderColor) {
        cardElement.style.borderColor = 'rgba(255, 255, 255, 0.15)';
      }
    }
    if (style.borderColor) cardElement.style.borderColor = style.borderColor;
    if (style.borderStyle) cardElement.style.borderStyle = style.borderStyle;
  }

  function getSavedGlobalStyle() {
    try { return JSON.parse(localStorage.getItem('bi_dashboard_global_style') || '{}') || {}; } catch (e) { return {}; }
  }

  // ── Ajout d'un visuel ──
  // Retourne TOUJOURS un id (ou lève une erreur explicite — CORRECTIF 1).
  function addVisual(config) {
    const grid = document.getElementById('visuals-grid');
    if (!grid) {
      throw new Error('[Dashboard.addVisual] #visuals-grid introuvable dans le DOM');
    }
    if (!config || typeof config !== 'object') {
      throw new Error('[Dashboard.addVisual] config invalide');
    }

    // Supprime l'état vide si présent
    const emptyCard = grid.querySelector('.empty-dataset-card');
    if (emptyCard) emptyCard.remove();

    visualCounter++;
    const cardId = `visual-card-${visualCounter}`;
    activeCardId = cardId;
    const chartBoxId = `chart-box-${visualCounter}`;

    const card = document.createElement('div');
    card.id = cardId;
    card.className = 'visual-card newly-added';

    const containerStyle = config.containerStyle || Object.assign({
      backgroundColor: 'rgba(17, 24, 39, 0.85)',
      backdropFilter: 'blur(12px)',
      borderRadius: '16px',
      boxShadow: '0 4px 14px rgba(0, 0, 0, 0.4)',
      border: '1px solid rgba(255, 255, 255, 0.08)'
    }, getSavedGlobalStyle());
    applyContainerStyle(card, containerStyle);

    if (config.chartType === 'card' || config.chartType === 'kpi_card') {
      card.innerHTML = `
        <div class="visual-card-header">
          <div class="visual-title-group">
            <h3>${config.title}</h3>
            <p>${config.subtitle || 'Visuel Card (Power BI Style)'}</p>
          </div>
          <div class="visual-tags">
            <span class="tag-badge chart-type">KPI CARD</span>
            <span class="tag-badge domain">${config.domain || 'MESURE'}</span>
          </div>
        </div>
        <div id="${chartBoxId}" class="visual-chart-box kpi-card-box">
          <div class="kpi-card-inner">
            <div class="kpi-card-number">${config.cardValueFormatted || config.cardValue || '$0'}</div>
            <div class="kpi-card-metric-name">${config.metricLabel || config.title}</div>
            <div class="kpi-card-benchmark">${config.cardBenchmark || '● Mesure calculée en direct'}</div>
          </div>
        </div>
        <div class="visual-card-footer">
          <div class="footer-btn-group">
            <button class="btn-card-action" onclick="Dashboard.openFormatDrawer('${cardId}')"><span>Formater</span></button>
            <button class="btn-card-action" onclick="Dashboard.showDaxModal('${cardId}')"><span>DAX</span></button>
            <button class="btn-card-action" onclick="Dashboard.showSqlModal('${cardId}')"><span>⚙ SQL Superset</span></button>
          </div>
          <button class="btn-card-action danger" onclick="Dashboard.removeVisual('${cardId}')"><span>Supprimer</span></button>
        </div>
      `;
    } else {
      card.innerHTML = `
        <div class="visual-card-header">
          <div class="visual-title-group">
            <h3>${config.title}</h3>
            <p>${config.subtitle || "Généré par l'Agent BI"}</p>
          </div>
          <div class="visual-tags">
            <span class="tag-badge chart-type">${(config.chartType || 'BAR').toUpperCase()}</span>
            <span class="tag-badge domain">${config.domain || 'ANALYTICS'}</span>
          </div>
        </div>
        <div id="${chartBoxId}" class="visual-chart-box"></div>
        <div class="visual-card-footer">
          <div class="footer-btn-group">
            <button class="btn-card-action format-btn" onclick="Dashboard.openFormatDrawer('${cardId}')"><span>Formater</span></button>
            <button class="btn-card-action" onclick="Dashboard.showDaxModal('${cardId}')"><span>DAX</span></button>
            <button class="btn-card-action" onclick="Dashboard.showSqlModal('${cardId}')"><span>⚙ SQL Superset</span></button>
            <button class="btn-card-action" onclick="Dashboard.exportChart('${cardId}')"><span>Exporter Image</span></button>
          </div>
          <button class="btn-card-action danger" onclick="Dashboard.removeVisual('${cardId}')"><span>Supprimer</span></button>
        </div>
      `;
    }

    card.dataset.dax = config.dax || '-- Aucune mesure DAX spécifiée';
    card.dataset.sql = config.sql || '-- Aucune requête SQL spécifiée';
    card.dataset.title = config.title;
    if (config._agentSid) card.dataset.sid = config._agentSid;

    grid.prepend(card);

    visualRegistry[cardId] = {
      cardId: cardId,
      chartBoxId: chartBoxId,
      config: config,
      meta: Object.assign({}, config),
      containerStyle: containerStyle
    };

    if (config.chartType !== 'card' && config.chartType !== 'kpi_card') {
      setTimeout(() => {
        const chartDom = document.getElementById(chartBoxId);
        if (chartDom && window.echarts) {
          try {
            // Libère l'ancienne instance si elle existe
            if (chartInstances[cardId]) { try { chartInstances[cardId].dispose(); } catch (e) { } }
            const myChart = echarts.init(chartDom, null, { renderer: 'canvas' });
            const option = buildEChartsOption(config.chartType, config.data, config);
            myChart.setOption(option);
            chartInstances[cardId] = myChart;
            visualRegistry[cardId].chartInstance = myChart;
          } catch (e) {
            console.error('[Dashboard.addVisual] ECharts init failed', e);
          }
        }
        try { card.scrollIntoView({ behavior: 'smooth', block: 'start' }); } catch (e) { }
      }, 50);
    } else {
      setTimeout(() => { try { card.scrollIntoView({ behavior: 'smooth', block: 'start' }); } catch (e) { } }, 50);
    }

    updateVisualCount();
    return cardId;
  }

  // ── Mise à jour d'un visuel ──
  // CORRECTIF 2 : accepte un cfg complet (data/series/chartType/labelField/valueField...).
  // Si l'objet contient `data` OU `series` OU `chartType` → remplace reg.config.
  // Sinon → comportement legacy (fusion dans reg.meta).
  function updateVisual(cardId, newConfigOrMeta, newContainerStyle) {
    const reg = visualRegistry[cardId];
    if (!reg) return false;
    newConfigOrMeta = newConfigOrMeta || {};
    newContainerStyle = newContainerStyle || {};

    const looksLikeFullConfig = (
      Array.isArray(newConfigOrMeta.data) ||
      Array.isArray(newConfigOrMeta.series) ||
      'labelField' in newConfigOrMeta ||
      'valueField' in newConfigOrMeta ||
      ('chartType' in newConfigOrMeta && 'data' in newConfigOrMeta)
    );

    if (looksLikeFullConfig) {
      reg.config = Object.assign({}, reg.config, newConfigOrMeta);
      reg.meta = Object.assign({}, reg.config);
    } else {
      reg.config = Object.assign({}, reg.config, newConfigOrMeta);
      reg.meta = Object.assign({}, reg.meta, newConfigOrMeta);
    }
    reg.containerStyle = Object.assign({}, reg.containerStyle, newContainerStyle);

    const card = document.getElementById(cardId);
    if (!card) return false;
    applyContainerStyle(card, reg.containerStyle);

    // Propager la mise à jour à l'Agent BI et au backend/kpis_catalog si créé par prompt
    if (reg.config && reg.config._agentSid && window.BIAgent && typeof window.BIAgent.syncVisualFromDashboard === 'function') {
      try { window.BIAgent.syncVisualFromDashboard(reg.config._agentSid, reg.config, reg.containerStyle); } catch (e) { }
    }

    // Met à jour aussi les data-attributes (DAX / SQL / titre) si présents dans le nouveau cfg
    if (newConfigOrMeta.sql) card.dataset.sql = newConfigOrMeta.sql;
    if (newConfigOrMeta.dax) card.dataset.dax = newConfigOrMeta.dax;
    if (newConfigOrMeta.title) card.dataset.title = newConfigOrMeta.title;

    // Met à jour le titre / sous-titre dans le header
    const h3 = card.querySelector('.visual-card-header h3');
    if (h3 && reg.config.title) h3.textContent = reg.config.title;
    const sub = card.querySelector('.visual-card-header p');
    if (sub && reg.config.subtitle) sub.textContent = reg.config.subtitle;
    const chartBadge = card.querySelector('.tag-badge.chart-type');
    if (chartBadge && reg.config.chartType) chartBadge.textContent = (reg.config.chartType === 'kpi_card' ? 'KPI CARD' : reg.config.chartType.toUpperCase());

    // Re-render ECharts si nécessaire
    const isCard = reg.config.chartType === 'card' || reg.config.chartType === 'kpi_card';
    if (isCard) {
      // Met à jour le contenu de la carte
      const box = card.querySelector('.kpi-card-inner');
      if (box) {
        const num = box.querySelector('.kpi-card-number');
        const mname = box.querySelector('.kpi-card-metric-name');
        const bench = box.querySelector('.kpi-card-benchmark');
        if (num) num.textContent = reg.config.cardValueFormatted || reg.config.cardValue || '$0';
        if (mname) mname.textContent = reg.config.metricLabel || reg.config.title || '';
        if (bench) bench.textContent = reg.config.cardBenchmark || '● Mesure calculée en direct';
      }
    } else {
      const chart = chartInstances[cardId];
      if (chart) {
        try {
          const updatedOption = buildEChartsOption(reg.config.chartType, reg.config.data, reg.config);
          chart.setOption(updatedOption, true);
          chart.resize();
        } catch (e) {
          console.error('[Dashboard.updateVisual] ECharts setOption failed', e);
        }
      } else {
        // Instance absente : tente de l'initialiser (cas où le setTimeout d'addVisual n'a pas encore tourné)
        setTimeout(() => {
          const chartDom = document.getElementById(reg.chartBoxId);
          if (chartDom && window.echarts && !chartInstances[cardId]) {
            try {
              const myChart = echarts.init(chartDom, null, { renderer: 'canvas' });
              myChart.setOption(buildEChartsOption(reg.config.chartType, reg.config.data, reg.config), true);
              chartInstances[cardId] = myChart;
              reg.chartInstance = myChart;
            } catch (e) { console.error(e); }
          }
        }, 30);
      }
    }

    return true;
  }

  // ── Suppression ──
  function removeVisual(cardId) {
    const card = document.getElementById(cardId);
    if (card) {
      const reg = visualRegistry[cardId];
      const sid = (reg && reg.config && reg.config._agentSid) || (card.dataset && card.dataset.sid);
      if (chartInstances[cardId]) {
        try { chartInstances[cardId].dispose(); } catch (e) { }
        delete chartInstances[cardId];
      }
      delete visualRegistry[cardId];
      card.remove();
      updateVisualCount();
      if (activeCardId === cardId) {
        const remaining = Object.keys(visualRegistry);
        activeCardId = remaining.length > 0 ? remaining[0] : null;
      }
      // Supprimer immédiatement de l'agent et du backend / kpis_catalog.json
      if (window.BIAgent && typeof window.BIAgent.deleteVisual === 'function') {
        try { window.BIAgent.deleteVisual(sid || cardId); } catch (e) { }
      }
    }
  }

  function updateVisualCount() {
    const count = document.querySelectorAll('.visual-card').length;
    const el = document.getElementById('visuals-count-badge');
    if (el) el.textContent = `${count} Visuel${count > 1 ? 's' : ''} Actif${count > 1 ? 's' : ''}`;
  }

  function exportChart(cardId) {
    const chart = chartInstances[cardId];
    if (!chart) return;
    const url = chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#111827' });
    const a = document.createElement('a');
    a.href = url;
    a.download = `chart_${cardId}.png`;
    a.click();
  }

  function showDaxModal(cardId) {
    const card = document.getElementById(cardId);
    if (!card) return;
    const dax = card.dataset.dax;
    const title = card.dataset.title;
    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body-content');
    if (!modalTitle || !modalBody) return;
    modalTitle.textContent = `Mesure DAX : ${title}`;
    modalBody.innerHTML = `
      <p style="margin-bottom: 8px; color: var(--text-secondary);">Cette mesure DAX peut être directement importée dans Microsoft Power BI Desktop ou votre modèle tabulaire Analysis Services :</p>
      <div class="json-code-box">${escapeHtml(dax)}</div>
      <button class="btn-header primary" style="margin-top: 14px;" onclick="navigator.clipboard.writeText(\`${dax.replace(/`/g, '\\`')}\`); alert('Mesure DAX copiée dans le presse-papier !');">Copier la formule DAX</button>
    `;
    const modal = document.getElementById('generic-modal');
    if (modal) modal.classList.add('active');
  }

  function showSqlModal(cardId) {
    const card = document.getElementById(cardId);
    if (!card) return;
    const sql = card.dataset.sql || '-- Aucune requête SQL spécifiée';
    const title = card.dataset.title || 'Visuel';
    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body-content');
    if (!modalTitle || !modalBody) return;
    modalTitle.textContent = `Requête SQL Apache Superset : ${title}`;
    modalBody.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <span style="font-size:12px; color:var(--accent-cyan); font-weight:600;">⚡ Apache Superset Engine (SQL Lab / Virtual Dataset)</span>
        <span class="tag-badge domain">SQL STANDARDIZED</span>
      </div>
      <p style="margin-bottom: 10px; color: var(--text-secondary); font-size:12px;">
        Cette requête SQL est prête à alimenter un dataset virtuel ou une tranche ECharts (bar, line, pie) sous <strong>Apache Superset</strong> :
      </p>
      <div class="json-code-box" style="color:#38bdf8;">${escapeHtml(sql)}</div>
      
      <div style="display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap;">
        <button class="btn-header primary" onclick="Dashboard.testSql('${cardId}')">
          <span>▶</span> Tester / Exécuter la Requête
        </button>
        <button class="btn-header" onclick="navigator.clipboard.writeText(\`${sql.replace(/`/g, '\\`')}\`); alert('Requête SQL copiée dans le presse-papier !');">
          <span>📋</span> Copier la requête SQL
        </button>
      </div>

      <div id="sql-execution-result-${cardId}" style="margin-top:14px;"></div>
    `;
    const modal = document.getElementById('generic-modal');
    if (modal) modal.classList.add('active');
  }

  async function testSql(cardId) {
    const card = document.getElementById(cardId);
    if (!card) return;
    const sql = card.dataset.sql;
    const resBox = document.getElementById(`sql-execution-result-${cardId}`);
    if (!resBox) return;
    resBox.innerHTML = '<div style="color:var(--text-muted); font-size:12px; padding:8px 0;"><span class="thinking-dots">⏳ Exécution de la requête SQL via le moteur SQLite / Superset…</span></div>';
    try {
      const t0 = performance.now();
      const r = await fetch('/api/agent/execute-sql', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sql })
      });
      const t1 = performance.now();
      const duration = (t1 - t0).toFixed(0);
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${r.status}`);
      }
      const data = await r.json();
      const rows = data.rows || [];
      if (!rows.length) {
        resBox.innerHTML = `<div style="padding:10px; background:rgba(255,255,255,0.05); border-radius:6px; color:#f59e0b; font-size:12px;">✓ Requête valide (${duration}ms) — 0 ligne retournée.</div>`;
        return;
      }
      const cols = Object.keys(rows[0]);
      let tableHtml = `<div style="margin-top:8px; font-size:11px; color:#10b981; margin-bottom:6px;">✓ Requête exécutée avec succès : <b>${rows.length}</b> lignes retournées (${duration}ms)</div>`;
      tableHtml += `<div style="max-height:220px; overflow:auto; border:1px solid rgba(255,255,255,0.1); border-radius:6px;">`;
      tableHtml += `<table style="width:100%; border-collapse:collapse; font-size:11px; text-align:left;">`;
      tableHtml += `<thead><tr style="background:rgba(255,255,255,0.08); color:#e2e8f0;">`;
      cols.forEach(c => { tableHtml += `<th style="padding:6px 10px; border-bottom:1px solid rgba(255,255,255,0.1);">${escapeHtml(c)}</th>`; });
      tableHtml += `</tr></thead><tbody>`;
      rows.slice(0, 10).forEach((row, idx) => {
        const bg = idx % 2 === 0 ? 'rgba(255,255,255,0.02)' : 'transparent';
        tableHtml += `<tr style="background:${bg}; border-bottom:1px solid rgba(255,255,255,0.04);">`;
        cols.forEach(c => { tableHtml += `<td style="padding:6px 10px; color:#cbd5e1;">${escapeHtml(String(row[c] ?? ''))}</td>`; });
        tableHtml += `</tr>`;
      });
      tableHtml += `</tbody></table></div>`;
      if (rows.length > 10) {
        tableHtml += `<div style="font-size:10px; color:var(--text-muted); margin-top:4px;">Affichage des 10 premières lignes sur ${rows.length}.</div>`;
      }
      resBox.innerHTML = tableHtml;
    } catch (e) {
      resBox.innerHTML = `<div style="padding:10px; background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.3); border-radius:6px; color:#f87171; font-size:12px;">⚠ Erreur lors de l'exécution : ${escapeHtml(e.message)}<br/><span style="font-size:11px; color:var(--text-muted);">Assurez-vous que le serveur python est en ligne et que la table correspondante est chargée.</span></div>`;
    }
  }

  // ── Drawer de formatage ──
  function openFormatDrawer(cardId) {
    activeCardId = cardId;
    const reg = visualRegistry[cardId];
    if (!reg) return;
    const drawer = document.getElementById('format-drawer');
    const titleEl = document.getElementById('drawer-target-title');
    if (titleEl) titleEl.textContent = reg.config.title;

    const meta = reg.meta;
    const style = reg.containerStyle;
    const isPie = reg.config.chartType === 'pie' || reg.config.chartType === 'donut';
    const isBar = reg.config.chartType === 'bar' || reg.config.chartType === 'echarts_bar';

    const chartSection = document.getElementById('drawer-chart-options');
    if (chartSection) {
      if (isPie) {
        chartSection.innerHTML = `
          <div class="format-group">
            <label class="format-label">Position des étiquettes (Labels)</label>
            <select class="format-select" id="fmt-label-position" onchange="Dashboard.applyDrawerChanges()">
              <option value="outside" ${meta.labelPosition === 'outside' ? 'selected' : ''}>Extérieur avec ligne (Outside)</option>
              <option value="inside" ${meta.labelPosition === 'inside' ? 'selected' : ''}>Intérieur (Inside)</option>
              <option value="none" ${meta.labelPosition === 'none' ? 'selected' : ''}>Masquées (None)</option>
            </select>
          </div>
          <div class="format-group">
            <label class="format-label">Format de l'étiquette</label>
            <select class="format-select" id="fmt-label-format" onchange="Dashboard.applyDrawerChanges()">
              <option value="both" ${meta.labelFormat !== 'percent_only' && meta.labelFormat !== 'value_only' ? 'selected' : ''}>Valeur et Pourcentage ({b}: {c} ({d}%))</option>
              <option value="percent_only" ${meta.labelFormat === 'percent_only' ? 'selected' : ''}>Pourcentage uniquement ({d}%)</option>
              <option value="value_only" ${meta.labelFormat === 'value_only' ? 'selected' : ''}>Valeur brute uniquement ({c})</option>
            </select>
          </div>
        `;
      } else if (isBar) {
        chartSection.innerHTML = `
          <div class="format-group">
            <label class="format-label">Couleur des barres</label>
            <div style="display: flex; gap: 8px; align-items: center;">
              <input type="color" class="format-color-picker" id="fmt-bar-color" value="${meta.barColor && meta.barColor.startsWith('#') ? meta.barColor : '#3b82f6'}" onchange="Dashboard.applyDrawerChanges()">
              <span style="font-size: 11px; color: var(--text-muted);">Palette Power BI</span>
            </div>
          </div>
          <div class="format-group">
            <label class="format-label">Étiquettes de données sur les barres</label>
            <label class="toggle-switch">
              <input type="checkbox" id="fmt-data-labels" ${meta.showDataLabels ? 'checked' : ''} onchange="Dashboard.applyDrawerChanges()">
              <span class="slider"></span>
            </label>
          </div>
          <div class="format-group">
            <label class="format-label">Axe Y - Échelle & Limites</label>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
              <div>
                <span style="font-size: 11px; color: var(--text-muted);">Min :</span>
                <input type="number" class="format-input" id="fmt-yaxis-min" placeholder="Auto" value="${meta.yAxisMin !== undefined && meta.yAxisMin !== null ? meta.yAxisMin : ''}" onchange="Dashboard.applyDrawerChanges()">
              </div>
              <div>
                <span style="font-size: 11px; color: var(--text-muted);">Max :</span>
                <input type="number" class="format-input" id="fmt-yaxis-max" placeholder="Auto" value="${meta.yAxisMax !== undefined && meta.yAxisMax !== null ? meta.yAxisMax : ''}" onchange="Dashboard.applyDrawerChanges()">
              </div>
            </div>
            <div style="margin-top: 6px;">
              <span style="font-size: 11px; color: var(--text-muted);">Pas / Intervalle (Saut de valeur) :</span>
              <input type="number" class="format-input" id="fmt-yaxis-interval" placeholder="Auto" value="${meta.yAxisInterval !== undefined && meta.yAxisInterval !== null ? meta.yAxisInterval : ''}" onchange="Dashboard.applyDrawerChanges()">
            </div>
          </div>
        `;
      } else {
        chartSection.innerHTML = `<p style="font-size: 12px; color: var(--text-muted);">Options graphiques standards pour ce type de visuel.</p>`;
      }
    }

    const blurInput = document.getElementById('fmt-blur-range');
    if (blurInput) {
      const blurVal = parseInt((style.backdropFilter || 'blur(12px)').replace(/[^0-9]/g, '')) || 12;
      blurInput.value = blurVal;
      const lbl = document.getElementById('fmt-blur-value');
      if (lbl) lbl.textContent = blurVal + 'px';
    }
    const radiusInput = document.getElementById('fmt-radius-range');
    if (radiusInput) {
      const radiusVal = parseInt(String(style.borderRadius || '16px').replace(/[^0-9]/g, '')) || 16;
      radiusInput.value = radiusVal;
      const lbl = document.getElementById('fmt-radius-value');
      if (lbl) lbl.textContent = radiusVal + 'px';
    }
    const shadowSelect = document.getElementById('fmt-shadow-select');
    if (shadowSelect) {
      if (style.boxShadow === 'none') shadowSelect.value = 'none';
      else if (style.boxShadow && style.boxShadow.includes('rgba(59, 130, 246')) shadowSelect.value = 'neon_blue';
      else if (style.boxShadow && style.boxShadow.includes('rgba(139, 92, 246')) shadowSelect.value = 'neon_purple';
      else shadowSelect.value = 'soft';
    }
    const bgSelect = document.getElementById('fmt-bg-select');
    if (bgSelect) {
      let opt = bgSelect.querySelector('option[value="custom"]');
      if (!opt) { opt = document.createElement('option'); opt.value = 'custom'; bgSelect.appendChild(opt); }
      const presets = { 'rgba(17, 24, 39, 0.88)': 'dark_slate', 'rgba(10, 10, 15, 0.94)': 'deep_black', 'rgba(255, 255, 255, 0.04)': 'glass_transparent' };
      const bgc = style.backgroundColor || 'rgba(17, 24, 39, 0.88)';
      if (presets[bgc]) { bgSelect.value = presets[bgc]; opt.hidden = true; }
      else { opt.textContent = 'Personnalisé (' + bgc + ')'; opt.hidden = false; bgSelect.value = 'custom'; }
    }

    if (drawer) drawer.classList.add('active');
  }

  function closeFormatDrawer() {
    const drawer = document.getElementById('format-drawer');
    if (drawer) drawer.classList.remove('active');
  }

  function applyDrawerChanges() {
    if (!activeCardId) return;

    const newMeta = {};
    const newContainerStyle = {};

    const labelPosEl = document.getElementById('fmt-label-position');
    if (labelPosEl) newMeta.labelPosition = labelPosEl.value;
    const labelFmtEl = document.getElementById('fmt-label-format');
    if (labelFmtEl) newMeta.labelFormat = labelFmtEl.value;
    const barColorEl = document.getElementById('fmt-bar-color');
    if (barColorEl) newMeta.barColor = barColorEl.value;
    const dataLabelsEl = document.getElementById('fmt-data-labels');
    if (dataLabelsEl) newMeta.showDataLabels = dataLabelsEl.checked;

    const yMinEl = document.getElementById('fmt-yaxis-min');
    if (yMinEl) newMeta.yAxisMin = yMinEl.value !== '' ? Number(yMinEl.value) : null;
    const yMaxEl = document.getElementById('fmt-yaxis-max');
    if (yMaxEl) newMeta.yAxisMax = yMaxEl.value !== '' ? Number(yMaxEl.value) : null;
    const yIntEl = document.getElementById('fmt-yaxis-interval');
    if (yIntEl) newMeta.yAxisInterval = yIntEl.value !== '' ? Number(yIntEl.value) : null;

    const blurRange = document.getElementById('fmt-blur-range');
    if (blurRange) {
      const b = blurRange.value;
      const lbl = document.getElementById('fmt-blur-value');
      if (lbl) lbl.textContent = b + 'px';
      newContainerStyle.backdropFilter = `blur(${b}px)`;
    }
    const radiusRange = document.getElementById('fmt-radius-range');
    if (radiusRange) {
      const r = radiusRange.value;
      const lbl = document.getElementById('fmt-radius-value');
      if (lbl) lbl.textContent = r + 'px';
      newContainerStyle.borderRadius = `${r}px`;
    }
    const shadowSelect = document.getElementById('fmt-shadow-select');
    if (shadowSelect) {
      const v = shadowSelect.value;
      if (v === 'none') newContainerStyle.boxShadow = 'none';
      if (v === 'soft') newContainerStyle.boxShadow = '0 6px 18px rgba(0, 0, 0, 0.45)';
      if (v === 'neon_blue') newContainerStyle.boxShadow = '0 0 25px rgba(59, 130, 246, 0.55)';
      if (v === 'neon_purple') newContainerStyle.boxShadow = '0 0 25px rgba(139, 92, 246, 0.55)';
    }
    const bgSelect = document.getElementById('fmt-bg-select');
    if (bgSelect) {
      const bg = bgSelect.value;
      if (bg === 'dark_slate') newContainerStyle.backgroundColor = 'rgba(17, 24, 39, 0.88)';
      if (bg === 'deep_black') newContainerStyle.backgroundColor = 'rgba(10, 10, 15, 0.94)';
      if (bg === 'glass_transparent') newContainerStyle.backgroundColor = 'rgba(255, 255, 255, 0.04)';
    }

    updateVisual(activeCardId, newMeta, newContainerStyle);
  }

  function escapeHtml(text) {
    return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ── Helper conversion KPI -> Visual Config ──
  function kpiToVisualConfig(kpi) {
    if (!kpi) return null;
    const chartType = kpi.chart_type || (kpi.superset_chart_type === 'echarts_pie' ? 'pie' : kpi.superset_chart_type === 'echarts_line' ? 'line' : 'bar');
    const data = kpi._data || [];
    if (!data.length && chartType !== 'card') return null;
    const keys = data.length ? Object.keys(data[0]) : [];
    const dc = kpi.dimension_column;
    const labelField = dc && keys.includes(dc) ? dc : (keys[0] || 'label');
    const numKeys = keys.filter(k => k !== labelField);
    const valueField = numKeys[0] || (keys[1] || 'value');
    const rawVal = kpi.raw_value !== undefined ? kpi.raw_value : (kpi.current_value !== undefined ? kpi.current_value : 0);
    const fmtVal = kpi.current_value_formatted || (typeof rawVal === 'number' ? formatValue(rawVal, 'auto') : String(rawVal));
    return {
      title: kpi.name,
      subtitle: `Dataset: ${kpi.source_file || kpi.source_table || ''} | Superset SQL`,
      chartType: chartType,
      domain: kpi.domain || 'ANALYTICS',
      data: data,
      labelField: labelField,
      valueField: valueField,
      metricLabel: kpi.metric_column || kpi.name,
      dax: kpi.dax_measure || '-- Mesure DAX',
      sql: kpi.sql_superset || '-- Requête SQL',
      kpi_id: kpi.id,
      source_file: kpi.source_file || '',
      cardValue: rawVal,
      cardValueFormatted: fmtVal,
      cardBenchmark: kpi.description || 'Mesure calculée en direct'
    };
  }

  // ── Nettoyage complet des visuels ──
  function clearAllVisuals() {
    Object.keys(chartInstances).forEach(id => {
      try { if (chartInstances[id]) chartInstances[id].dispose(); } catch (e) { }
      delete chartInstances[id];
    });
    Object.keys(visualRegistry).forEach(k => delete visualRegistry[k]);
    visualCounter = 0;
    activeCardId = null;
    const grid = document.getElementById('visuals-grid');
    if (grid) grid.innerHTML = '';
    updateVisualCount();
  }

  // ── État vide lorsque aucun dataset n'a encore été importé ──
  function showEmptyDatasetState() {
    const grid = document.getElementById('visuals-grid');
    if (!grid || Object.keys(visualRegistry).length > 0) return;
    grid.innerHTML = `
      <div class="empty-dataset-card" style="grid-column: 1 / -1; padding: 56px 24px; text-align: center; background: rgba(17, 24, 39, 0.65); border: 2px dashed rgba(56, 189, 248, 0.35); border-radius: 18px; backdrop-filter: blur(14px); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px;">
        <div style="font-size: 52px; line-height: 1;">📂</div>
        <h3 style="font-size: 22px; font-weight: 600; color: #f3f4f6; margin: 0;">Aucun Dataset Actif Sélectionné</h3>
        <p style="max-width: 560px; color: #94a3b8; font-size: 14px; margin: 0; line-height: 1.6;">
          Parcourez et sélectionnez votre fichier <strong>Excel (.xlsx, .xls)</strong> ou <strong>CSV</strong> depuis votre ordinateur.<br/>
          L'agent déterminera automatiquement la structure des données, générera vos KPIs dans <code>kpis_catalog.json</code> et affichera votre tableau de bord interactif !
        </p>
        <button class="btn-primary" style="padding: 12px 28px; font-size: 15px; font-weight: 600; display: inline-flex; align-items: center; gap: 10px; cursor: pointer; border-radius: 10px; background: linear-gradient(135deg, #2563eb, #3b82f6); color: white; border: none; box-shadow: 0 4px 16px rgba(37, 99, 235, 0.45); transition: transform 0.15s ease;" onclick="document.getElementById('bi-dataset-upload-input').click()">
          <span style="font-size: 18px;">📂</span>
          <span>Parcourir un Fichier (Excel / CSV)</span>
        </button>
      </div>
    `;
  }

  // ── Chargement dynamique des visuels du Dataset actif (Catalogue JSON / API) ──
  async function seedDefaultCharts() {
    let loaded = false;
    const grid = document.getElementById('visuals-grid');

    // 0. Chargement synchrone immédiat depuis les scripts injectés (visuals_state.js ou data_store.js)
    const syncVisuals = (window.VISUALS_STATE && Array.isArray(window.VISUALS_STATE.visuals) && window.VISUALS_STATE.visuals.length > 0)
      ? window.VISUALS_STATE.visuals
      : (window.KPIS_CATALOG && Array.isArray(window.KPIS_CATALOG.auto_visuals) && window.KPIS_CATALOG.auto_visuals.length > 0)
        ? window.KPIS_CATALOG.auto_visuals
        : null;

    if (syncVisuals && syncVisuals.length > 0) {
      if (grid) {
        const empty = grid.querySelector('.empty-dataset-card');
        if (empty) empty.remove();
      }
      syncVisuals.forEach(v => {
        try { addVisual(v); loaded = true; } catch (e) { console.warn('addVisual sync error', e); }
      });
      if (loaded) {
        updateVisualCount();
        return;
      }
    }

    try {
      const resp = await fetch('/api/agent/visuals/seed', { signal: AbortSignal.timeout(2500) });
      if (resp.ok) {
        const payload = await resp.json();
        const visuals = payload.visuals || [];
        if (visuals.length > 0) {
          visuals.slice(0, 8).forEach(v => {
            try { addVisual(v); loaded = true; } catch (e) { console.warn('addVisual error', e); }
          });
        }
      }
    } catch (_) { }

    if (loaded) return;

    try {
      let catalog = window.KPIS_CATALOG;
      if (!catalog) {
        const r = await fetch('kpis_catalog.json?_t=' + Date.now(), { signal: AbortSignal.timeout(2500) });
        if (r.ok) {
          catalog = await r.json();
          window.KPIS_CATALOG = catalog;
        }
      }
      // 1. Auto visuals
      if (catalog && Array.isArray(catalog.auto_visuals) && catalog.auto_visuals.length > 0) {
        catalog.auto_visuals.slice(0, 8).forEach(v => {
          try { addVisual(v); loaded = true; } catch (e) { console.warn("addVisual auto_visual error", e); }
        });
      }

      // 2. visuals_state.json fallback
      if (!loaded) {
        try {
          const vsResp = await fetch("visuals_state.json?_t=" + Date.now(), { signal: AbortSignal.timeout(2000) });
          if (vsResp.ok) {
            const vsPayload = await vsResp.json();
            const visuals = vsPayload.visuals || [];
            if (visuals.length > 0) {
              visuals.slice(0, 8).forEach(v => {
                try { addVisual(v); loaded = true; } catch (e) { console.warn("addVisual vs error", e); }
              });
            }
          }
        } catch (_) { }
      }

      // 3. nonCardKpis
      if (!loaded && catalog && Array.isArray(catalog.kpis)) {
        const nonCardKpis = catalog.kpis.filter(k => k.active !== false && k.chart_type !== 'card' && Array.isArray(k._data) && k._data.length > 0);
        if (nonCardKpis.length > 0) {
          nonCardKpis.slice(0, 8).forEach(k => {
            const vc = kpiToVisualConfig(k);
            if (vc) { addVisual(vc); loaded = true; }
          });
        }
      }
    } catch (_) { }

    if (loaded) return;

    // Si aucun visuel n'est encore disponible : afficher l'état invitant à parcourir un fichier
    showEmptyDatasetState();
  }

  // ── Importation dynamique de Dataset (CSV, XLS, XLSX) ──
  async function importDatasetFile(file) {
    if (!file) return;
    const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
    if (!['.csv', '.xlsx', '.xls'].includes(ext)) {
      alert("Format non supporté. Veuillez importer un fichier .csv, .xls ou .xlsx.");
      return;
    }

    // Réinitialise immédiatement les anciens visuels
    clearAllVisuals();

    const grid = document.getElementById('visuals-grid');
    if (grid) {
      grid.innerHTML = `
        <div class="empty-dataset-card" style="grid-column: 1 / -1; padding: 48px 24px; text-align: center; background: rgba(17, 24, 39, 0.65); border: 1px solid rgba(56, 189, 248, 0.35); border-radius: 16px; backdrop-filter: blur(12px); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px;">
          <div class="thinking-dots" style="font-size: 32px;">⏳</div>
          <h3 style="font-size: 19px; font-weight: 600; color: #f3f4f6; margin: 0;">Analyse et Ingestion du Dataset…</h3>
          <p style="color: #94a3b8; font-size: 14px; margin: 0;">Extraction du schéma, calcul des KPIs et mise à jour de <code>kpis_catalog.json</code> pour <strong>${escapeHtml(file.name)}</strong>.</p>
        </div>
      `;
    }

    if (window.Agent && window.Agent._appendMessage) {
      window.Agent._appendMessage('user', `📂 Importer le dataset : <b>${escapeHtml(file.name)}</b>`);
      window.Agent._appendMessage('agent', `<span class="thinking-dots">⏳ Analyse, ingestion et extraction des KPIs & requêtes SQL pour <b>${escapeHtml(file.name)}</b>…</span>`);
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
      const resp = await fetch('/api/agent/upload', {
        method: 'POST',
        body: formData
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error || `Erreur serveur HTTP ${resp.status}`);
      }
      const data = await resp.json();

      // Mettre à jour window.KPIS_CATALOG depuis le serveur
      try {
        const catResp = await fetch('kpis_catalog.json?_t=' + Date.now());
        if (catResp.ok) window.KPIS_CATALOG = await catResp.json();
      } catch (_) { }

      // Vider l'indicateur de chargement
      if (grid) grid.innerHTML = '';

      // Générer les visuels reçus pour ce dataset
      const newVisuals = data.visuals || [];
      if (newVisuals.length > 0) {
        newVisuals.forEach(v => {
          try { addVisual(v); } catch (e) { console.warn('addVisual error', e); }
        });
      } else {
        // Repli sur les KPIs du catalogue
        const catalog = window.KPIS_CATALOG || {};
        const nonCards = (catalog.kpis || []).filter(k => k.chart_type !== 'card' && Array.isArray(k._data) && k._data.length > 0);
        nonCards.forEach(k => {
          const vc = kpiToVisualConfig(k);
          if (vc) addVisual(vc);
        });
      }

      // Mettre à jour les KPI cards en haut de page
      initSummaryCards(window.KPIS_CATALOG);

      // Mettre à jour la pastille du header avec le nom du dataset actif
      const pill = document.querySelector('.dataset-pill') || document.getElementById('dataset-status-pill');
      if (pill) {
        pill.innerHTML = `● Dataset actif : <strong>${escapeHtml(data.filename)}</strong> (${data.n_rows} lignes, ${data.n_kpis} KPIs)`;
      }

      // Alimenter dynamiquement BI_DATA_STORE avec les lignes du fichier pour l'agent conversationnel
      if (data.table_name && Array.isArray(data.rows)) {
        window.BI_DATA_STORE = window.BI_DATA_STORE || {};
        window.BI_DATA_STORE[data.table_name] = data.rows;
      }

      // Rafraîchir l'Agent BI et son index RAG
      if (window.BIAgent) {
        try {
          if (window.BIAgent._resetCatalog) window.BIAgent._resetCatalog();
          const internalCat = window.BIAgent.getCatalog ? window.BIAgent.getCatalog() : null;
          if (window.BIAgent.getRAGStore) {
            window.BIAgent.getRAGStore().build(window.BI_DATA_STORE, internalCat || window.KPIS_CATALOG);
          }
        } catch (eRAG) {
          console.warn('[Dashboard.importDatasetFile] RAG refresh warning:', eRAG);
        }
      }

      if (window.Agent && window.Agent._appendMessage) {
        window.Agent._appendMessage('agent',
          `✅ <strong>Dataset « ${escapeHtml(data.filename)} » ingéré avec succès !</strong><br/>` +
          `• <strong>${data.n_rows}</strong> lignes indexées (Table SQL : <code>${escapeHtml(data.table_name)}</code>)<br/>` +
          `• <strong>${data.n_kpis}</strong> nouveaux KPIs calculés & intégrés dans <code>kpis_catalog.json</code><br/>` +
          `• <strong>${newVisuals.length}</strong> visuels générés sur votre tableau de bord.<br/>` +
          `Vous pouvez désormais interroger ces données ou ajuster les visuels par prompt !`
        );
      }
    } catch (err) {
      if (grid && Object.keys(visualRegistry).length === 0) showEmptyDatasetState();
      if (window.Agent && window.Agent._appendMessage) {
        window.Agent._appendMessage('agent', `⚠️ <strong>Échec de l'ingestion :</strong> ${escapeHtml(err.message)}`);
      } else {
        alert("Erreur lors de l'ingestion du fichier : " + err.message);
      }
    }
  }

  function handleFileInput(input) {
    if (input.files && input.files[0]) {
      importDatasetFile(input.files[0]);
      input.value = '';
    }
  }

  async function refreshFromCatalog() {
    try {
      const catResp = await fetch('kpis_catalog.json?_t=' + Date.now());
      if (catResp.ok) {
        window.KPIS_CATALOG = await catResp.json();
        initSummaryCards(window.KPIS_CATALOG);
      }
    } catch (e) { console.warn('refreshFromCatalog error', e); }
  }

  // ── Redimensionnement ──
  if (typeof window !== 'undefined' && window.addEventListener) {
    window.addEventListener('resize', () => {
      Object.values(chartInstances).forEach(chart => {
        if (chart) { try { chart.resize(); } catch (e) { } }
      });
    });
  }

  // ── Filtres & Styles Globaux (Power BI Style) ──
  let activeGlobalFilter = null;

  function applyGlobalFilter(filterSpec) {
    if (!filterSpec || filterSpec.clear) {
      activeGlobalFilter = null;
      Object.keys(visualRegistry).forEach(cardId => {
        const reg = visualRegistry[cardId];
        if (reg && reg.config && reg.config._rawOriginalData) {
          reg.config.data = [...reg.config._rawOriginalData];
          updateVisual(cardId, { data: reg.config.data });
        }
      });
      renderGlobalFilterPill(null);
      return { success: true, cleared: true, message: "Filtre global réinitialisé. Toutes les données sont restaurées." };
    }

    const { filterValues, topN } = filterSpec;
    activeGlobalFilter = filterSpec;
    const filterSet = (Array.isArray(filterValues) && filterValues.length)
      ? new Set(filterValues.map(v => String(v).toLowerCase().trim()))
      : null;

    let affected = 0;
    Object.keys(visualRegistry).forEach(cardId => {
      const reg = visualRegistry[cardId];
      if (!reg || !reg.config || !Array.isArray(reg.config.data) || !reg.config.data.length) return;

      if (!reg.config._rawOriginalData) {
        reg.config._rawOriginalData = [...reg.config.data];
      }
      const raw = reg.config._rawOriginalData;
      const labelField = reg.config.labelField;

      let filtered = raw;
      if (filterSet) {
        filtered = raw.filter(row => {
          const val = String((labelField && row[labelField]) || row.country || row.name || row.sector || row.category || row.comparison || Object.values(row)[0] || '').toLowerCase().trim();
          for (const target of filterSet) {
            if (val === target || val.includes(target) || target.includes(val)) return true;
          }
          return false;
        });
      }

      if (topN && Number(topN) > 0) {
        filtered = filtered.slice(0, Number(topN));
      }

      reg.config.data = filtered.length > 0 ? filtered : raw;
      updateVisual(cardId, { data: reg.config.data });
      affected++;
    });

    renderGlobalFilterPill(filterSpec);
    return {
      success: true,
      affected,
      filterValues: filterValues || [],
      topN: topN || null,
      message: `Filtre global appliqué sur ${affected} visuel(s) : ${filterValues ? filterValues.join(', ') : `Top ${topN}`}`
    };
  }

  function renderGlobalFilterPill(filterSpec) {
    let container = document.getElementById('global-filter-badge');
    const header = document.querySelector('.header-left') || document.querySelector('.dashboard-header');
    if (!filterSpec || filterSpec.clear) {
      if (container) container.remove();
      return;
    }
    const label = filterSpec.filterValues && filterSpec.filterValues.length
      ? filterSpec.filterValues.join(', ')
      : (filterSpec.topN ? `Top ${filterSpec.topN}` : 'Actif');

    if (!container) {
      container = document.createElement('div');
      container.id = 'global-filter-badge';
      container.style.cssText = 'display: inline-flex; align-items: center; gap: 8px; padding: 4px 12px; background: rgba(59, 130, 246, 0.2); border: 1px solid rgba(59, 130, 246, 0.45); border-radius: 20px; font-size: 12px; color: #93c5fd; margin-left: 10px;';
      if (header) header.appendChild(container);
    }
    container.innerHTML = `
      <span>🔍 <strong>Filtre Global :</strong> ${escapeHtml(label)}</span>
      <button style="background: none; border: none; color: #f87171; cursor: pointer; font-size: 13px; font-weight: bold; padding: 0 4px;" onclick="if (window.BIAgent && BIAgent.clearGlobalFilter) BIAgent.clearGlobalFilter(); else Dashboard.applyGlobalFilter({ clear: true }); if (window.Agent) window.Agent._appendMessage('agent', 'ℹ️ Filtre global du tableau de bord réinitialisé.');" title="Supprimer le filtre">✕</button>
    `;
  }

  function applyGlobalStyle(style) {
    if (!style || typeof style !== 'object') return;
    Object.keys(visualRegistry).forEach(cardId => {
      updateVisual(cardId, {}, style);
    });
    // Direct DOM reinforcement for instant visual feedback
    document.querySelectorAll('.visual-card').forEach(card => {
      applyContainerStyle(card, style);
    });
    try {
      localStorage.setItem('bi_dashboard_global_style', JSON.stringify(Object.assign({}, getSavedGlobalStyle(), style)));
    } catch (_) { }
  }

  // ── Changement de type ──
  function changeChartType(cardId, newType) {
    const reg = visualRegistry[cardId];
    if (!reg) return false;
    if (reg.config.chartType === 'card' || reg.config.chartType === 'kpi_card') return false;

    reg.config.chartType = newType;
    if (reg.meta) reg.meta.chartType = newType;

    const chartBadge = document.querySelector(`#${cardId} .tag-badge.chart-type`);
    if (chartBadge) chartBadge.textContent = String(newType).toUpperCase();

    const chart = chartInstances[cardId];
    if (chart) {
      try {
        const opt = buildEChartsOption(newType, reg.config.data, reg.config);
        chart.setOption(opt, true);
      } catch (e) { console.error(e); }
      return true;
    }

    setTimeout(() => {
      const chartDom = document.getElementById(reg.chartBoxId);
      if (chartDom && window.echarts) {
        try {
          if (chartInstances[cardId]) { try { chartInstances[cardId].dispose(); } catch (e) { } }
          const myChart = echarts.init(chartDom, null, { renderer: 'canvas' });
          myChart.setOption(buildEChartsOption(newType, reg.config.data, reg.config), true);
          chartInstances[cardId] = myChart;
          reg.chartInstance = myChart;
        } catch (e) { console.error(e); }
      }
    }, 60);
    return true;
  }
  function shadesOf(hex, n) {
    const h = String(hex || '').replace('#', ''); if (h.length !== 6) return [hex];
    const c = [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16));
    return Array.from({ length: Math.max(1, n) }, (_, i) => {
      const t = n > 1 ? (i / (n - 1)) * 0.6 : 0;
      return '#' + c.map(v => Math.round(v + (255 - v) * t).toString(16).padStart(2, '0')).join('');
    });
  }
  function applyGlobalMeta(meta, skipIds) {
    if (!meta || !Object.keys(meta).length) return 0;
    let n = 0;
    Object.keys(visualRegistry).forEach(id => {
      if (skipIds && skipIds.has && skipIds.has(id)) return;
      const reg = visualRegistry[id], t = reg && reg.config && reg.config.chartType;
      if (!t || t === 'card' || t === 'kpi_card') return;
      const m = Object.assign({}, meta);
      if (m.barColor || m.palette) {
        m.colors = undefined;
        if (!reg.config.comparison) m.categoryColors = undefined;
        if (!m.palette && ['pie', 'donut', 'treemap'].includes(t)) m.palette = shadesOf(m.barColor, (reg.config.data || []).length);
      }
      updateVisual(id, m, {}); n++;
    });
    return n;
  }

  // ── API publique ──
  return {
    init: async function () {
      try { restoreDashboardBackground(); } catch (e) { }
      try {
        if (!window.KPIS_CATALOG) {
          const r = await fetch('kpis_catalog.json?_t=' + Date.now());
          if (r.ok) window.KPIS_CATALOG = await r.json();
        }
      } catch (e) { }

      try {
        const cat = window.KPIS_CATALOG;
        const pill = document.querySelector('.dataset-pill') || document.getElementById('dataset-status-pill');
        if (pill && cat && cat.metadata && cat.metadata.active_dataset) {
          pill.innerHTML = `● Dataset actif : <strong>${escapeHtml(cat.metadata.active_dataset)}</strong> (${cat.metadata.n_rows || (cat.kpis && cat.kpis.length) || 0} lignes)`;
        }
      } catch (e) { }

      try { initSummaryCards(); } catch (e) { console.error('initSummaryCards', e); }
      try { seedDefaultCharts(); } catch (e) { console.error('seedDefaultCharts', e); }
      window.__DASHBOARD_READY__ = true;
    },
    setDashboardBackground: setDashboardBackground,
    restoreDashboardBackground: restoreDashboardBackground,
    addVisual: addVisual,
    updateVisual: updateVisual,
    removeVisual: removeVisual,
    exportChart: exportChart,
    showDaxModal: showDaxModal,
    showSqlModal: showSqlModal,
    testSql: testSql,
    importDatasetFile: importDatasetFile,
    handleFileInput: handleFileInput,
    refreshFromCatalog: refreshFromCatalog,
    openFormatDrawer: openFormatDrawer,
    closeFormatDrawer: closeFormatDrawer,
    applyDrawerChanges: applyDrawerChanges,
    formatValue: formatValue,
    changeChartType: changeChartType,
    applyGlobalFilter: applyGlobalFilter,
    applyGlobalStyle: applyGlobalStyle,
    buildEChartsOption: buildEChartsOption,
    list: function () {
      return Object.keys(visualRegistry).map(id => ({
        id,
        title: (visualRegistry[id].config && visualRegistry[id].config.title) || id
      }));
    },
    getActiveCardId: function () {
      return activeCardId && document.getElementById(activeCardId) ? activeCardId : null;
    },
    setActiveCardId: function (id) {
      if (id && (visualRegistry[id] || document.getElementById(id))) {
        activeCardId = id;
      }
    },
    getActiveOrLatestCardId: function () {
      if (activeCardId && document.getElementById(activeCardId)) return activeCardId;
      const keys = Object.keys(visualRegistry);
      return keys.length > 0 ? keys[0] : null;
    },
    getRegistry: function () { return visualRegistry; }
  };
})();