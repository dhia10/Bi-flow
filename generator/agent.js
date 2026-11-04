/**
 * BI Agent NL v5.5 — Prompt → SQL Superset, mémoire persistante, RAG correctif + agentique,
 *                     binnage binaire générique (meilleur/pire que N'IMPORTE QUEL pays) + Gemini.
 *
 *  NOUVEAUTÉS v5.4 (correctifs conversation / modification) :
 *   1. PROTECTED_ACTIONS : dashboard_bg, global_filter, delete, list, show, undo, explain, chat
 *      ne peuvent plus être écrasées par Ollama ni Gemini.
 *   2. normalizeTypos() : fautes de frappe corrigées dans le texte analysé (T et P).
 *   3. matchCountryLabel() sécurisé (plus de faux positifs : "plus" ≠ "us").
 *   4. detectComparisonSplit() : détecte le côté (meilleur / pire) et attribue la couleur au bon côté.
 *   5. resolveWithContext() : changement de pays de référence ("tunisie au lieu de france"),
 *      fusion des couleurs (le côté non cité est conservé), visuel nommé introuvable → liste des titres.
 *   6. findVisualByTitleOrPrompt() : recherche par titre plus stricte (ratio 60 %).
 *   7. Camembert de comparaison = NOMBRE de pays (champ count) et non moyenne du taux.
 *
 *  HÉRITAGE v5.3 : baseline générique, rate_usd par pays, fallback PIB.
 *  HÉRITAGE v5.2 : fallback Gemini si confiance < seuil.
 *  HÉRITAGE v5.1 : UPDATE FORCÉ, restore() non destructif, waitDashboard().
 */
(function () {
  'use strict';
  const root = (typeof window !== 'undefined') ? window : globalThis;
  const ORIGIN = (typeof window !== 'undefined' && window.location && window.location.origin && window.location.origin !== 'null') ? window.location.origin : null;

  /* ═══════════════════════ CONFIG ═══════════════════════ */
  const CFG = {
    useLLM: true,
    alwaysLLM: false,
    ollamaUrl: 'http://localhost:11434',
    ollamaProxyUrl: ORIGIN || null,
    model: 'llama3.2:3b',
    timeoutMs: 15000,
    catalogUrl: 'kpis_catalog.json',
    maxLLMEntries: 60,
    pieMaxSlices: 8,

    enableChaining: true,
    chainTimeout: 90000,
    autoModifyVisualOnError: true,
    forceExplicitChartType: true,

    persist: true,
    storageKeyVisuals: 'bi_agent_visuals_v5',
    storageKeyMemory: 'bi_agent_memory_v5',
    restoreWaitMs: 6000,
    memoryTurns: 100,
    llmHistoryTurns: 12,
    clarifyOptions: 4,

    sqlSchema: '',
    sqlTableMap: {},
    summaryTable: 'summary',

    chunkSize: 512, chunkOverlap: 64, maxChunks: 8, ragScoreThreshold: 0.04, bm25K1: 1.2, bm25B: 0.75,
    cragMinOverlap: 0.5, cragAmbiguous: 0.2, cragMaxRewrites: 2,
    agentMaxSteps: 4, agentUseLLM: true,

    loraEnabled: true,
    loraServerUrl: ORIGIN || 'http://localhost:8080',
    loraEndpoint: '/api/lora-train',
    dataFilesApiUrl: (ORIGIN || 'http://localhost:8080') + '/api/list-data-files',
    dataFileExtensions: ['.xls', '.xlsx', '.csv'],
    loraHyperparams: {
      learning_rate: 2e-4, lora_r: 8, lora_alpha: 16, lora_dropout: 0.05, num_epochs: 3,
      batch_size: 4, max_seq_length: 512, warmup_steps: 50, gradient_accumulation: 4,
      target_modules: ['q_proj', 'v_proj']
    },
    errorVisualEnabled: true,

    geminiEnabled: true,
    geminiApiKey: null,
    geminiModel: 'gemini-2.5-flash',
    geminiEndpoint: 'https://generativelanguage.googleapis.com/v1beta/models',
    geminiTimeoutMs: 12000,
    geminiConfidenceThreshold: 0.55
  };

  /* ═══════════════════════ UTILITAIRES ═══════════════════════ */
  const ascii = s => String(s == null ? '' : s).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  const stem = w => (w.length > 3 ? w.replace(/[sx]$/, '') : w);
  function normWords(s) {
    const w = ascii(s).replace(/[^a-z0-9]+/g, ' ').trim().split(' ').filter(Boolean).map(stem);
    return ' ' + w.join(' ') + ' ';
  }
  const has = (P, phrase) => { const n = normWords(phrase); return n.trim().length > 0 && P.indexOf(n) !== -1; };
  const humanize = s => String(s).replace(/[_\-]+/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').replace(/\b\w/g, c => c.toUpperCase());
  const isTimeName = k => /^(year|annee|date|month|mois|period|periode|quarter|trimestre)$/i.test(k);
  const uid = (p = 'pc_') => p + Math.random().toString(36).slice(2, 9);
  const escRe = s => String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const clone = o => JSON.parse(JSON.stringify(o));
  const clean1 = s => String(s == null ? '' : s).replace(/[\r\n]+/g, ' ');

  function lev(a, b) {
    const m = a.length, n = b.length; if (!m) return n; if (!n) return m;
    let prev = []; for (let j = 0; j <= n; j++) prev[j] = j;
    for (let i = 1; i <= m; i++) {
      const cur = [i];
      for (let j = 1; j <= n; j++) cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      prev = cur;
    }
    return prev[n];
  }
  function fuzzyScore(tok, term) {
    if (tok === term) return 1;
    if (tok.length < 5 || term.length < 5) return 0;
    const d = lev(tok, term), m = Math.max(tok.length, term.length);
    return (d <= 2 && d / m <= 0.25) ? 1 - d / m : 0;
  }
  function shades(hex, n) {
    const h = String(hex).replace('#', ''); if (h.length !== 6) return [hex];
    const c = [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16)), out = [];
    for (let i = 0; i < Math.max(1, n); i++) {
      const t = n > 1 ? (i / (n - 1)) * 0.6 : 0;
      out.push('#' + c.map(v => Math.round(v + (255 - v) * t).toString(16).padStart(2, '0')).join(''));
    }
    return out;
  }

  const Store = {
    ok() { try { return typeof localStorage !== 'undefined' && !!localStorage; } catch (e) { return false; } },
    get(k) { try { if (!Store.ok()) return null; const r = localStorage.getItem(k); return r ? JSON.parse(r) : null; } catch (e) { return null; } },
    set(k, v) { try { if (Store.ok()) localStorage.setItem(k, JSON.stringify(v)); } catch (e) { } }
  };

  /* ═══════════════════════ DICTIONNAIRES ═══════════════════════ */
  const SYN = {
    revenue: ["chiffre d'affaires", "chiffre d affaires", "chiffre d'affaire", 'revenu', 'revenus', 'revenue', 'recette', 'recettes', 'ventes', 'turnover'],
    market_cap: ['market cap', 'capitalisation', 'capitalisation boursiere', 'valorisation'],
    ebitda: ['ebitda', 'excedent brut d exploitation', 'marge operationnelle'],
    net_income: ['resultat net', 'benefice', 'benefices', 'profit', 'profits', 'net income', 'gain', 'gains'],
    income: ['resultat', 'benefice', 'profit'],
    count: ['nombre', 'volume', 'effectif', 'repartition', 'quantite', 'combien', 'count', 'pourcentage', 'part'],
    value: ['valeur', 'montant'],
    pe_ratio: ['p e', 'per', 'pe ratio', 'price earning'],
    ratio: ['ratio'],
    roe: ['roe', 'rentabilite des capitaux propres'],
    growth: ['croissance', 'growth'],
    inflation: ['inflation'],
    gdp: ['pib', 'gdp', 'produit interieur brut'],
    unemployment: ['chomage'],
    debt: ['dette'],
    rating: ['notation', 'rating'],
    currency: ['devise', 'devises', 'monnaie', 'currency', 'currencies', 'taux de change', 'change', 'usd', 'dollar', 'rate usd'],
    rate_usd: ['taux vs usd', 'taux de change', 'currency', 'devise', 'devises', 'usd', 'dollar', 'change', 'valeur devise', 'monnaie', 'meilleur que usa', 'pire que usa'],
    exchange: ['taux de change', 'change', 'devise', 'currency'],
    population: ['population'],
    employees: ['employe', 'effectif'],
    price: ['prix', 'cours'],
    sector: ['secteur', 'industrie', "secteur d'activite", 'sector'],
    country: ['pays', 'nation', 'nations', 'country', 'countries', 'geographie', 'etat'],
    category: ['categorie', 'type', 'theme', 'category'],
    year: ['annee', 'evolution', 'tendance', 'historique', 'par an', 'annuel', 'dans le temps', 'trend'],
    historical: ['historique'],
    trend: ['tendance', 'evolution'],
    events: ['evenement', 'actualite', 'veille', 'news', 'article', 'event'],
    event: ['evenement', 'actualite', 'veille'],
    fdi_inflow: ['fdi_inflow', 'fdi inflow', 'fdi', 'ide', 'flux ide', 'investissements directs', 'investissements etrangers', 'inflow', 'foreign direct investment'],
    gdp_growth: ['gdp_growth', 'gdp growth', 'croissance pib', 'croissance du pib', 'taux de croissance pib', 'pib growth', 'growth pct'],
    companies: ['entreprise', 'entreprises', 'societe', 'societes', 'client', 'clients', 'company', 'companies', 'compagnies'],
    company: ['entreprise', 'entreprises', 'societe', 'societes', 'client', 'clients', 'company', 'companies'],
    name: ['entreprise', 'entreprises', 'societe', 'societes', 'company', 'companies', 'nom', 'name', 'client', 'clients', 'leader', 'leaders']
  };
  const synFor = tok => SYN[tok] || SYN[tok.replace(/ies$/, 'y')] || SYN[tok.replace(/s$/, '')] || [];

  const LABELS = {
    revenue: "Chiffre d'affaires", market_cap: 'Market Cap', ebitda: 'EBITDA', net_income: 'Résultat net', count: 'Nombre',
    total_revenue: "Chiffre d'Affaires Global", total_market_cap: 'Market Cap Cumulé', total_ebitda: 'EBITDA Total',
    total_events: 'Événements & Veille', avg_pe_ratio: 'P/E Ratio Moyen', avg_roe: 'ROE Moyen',
    sector: 'Secteur', country: 'Pays', category: 'Catégorie', year: 'Année', name: 'Entreprise',
    rate_usd: 'Taux vs USD (Devise)', currency: 'Devise',
    fdi_inflow: 'FDI Inflow (Investissements Étrangers)', gdp_growth: 'Croissance du PIB (GDP Growth %)',
    gdp: 'PIB (GDP en Dollars)', inflation: 'Inflation (%)', unemployment: 'Chômage (%)'
  };
  const COLORS = {
    bleu: '#3b82f6', blue: '#3b82f6', rouge: '#ef4444', red: '#ef4444', vert: '#10b981', green: '#10b981',
    jaune: '#eab308', yellow: '#eab308', orange: '#f97316', violet: '#8b5cf6', purple: '#8b5cf6', mauve: '#8b5cf6',
    rose: '#ec4899', pink: '#ec4899', cyan: '#06b6d4', turquoise: '#06b6d4', gris: '#6b7280', gray: '#6b7280', grey: '#6b7280',
    noir: '#111827', black: '#111827', blanc: '#f9fafb', white: '#f9fafb'
  };
  Object.assign(COLORS, {
    marron: '#92400e', brun: '#78350f', beige: '#f5f0dc', dore: '#d4af37', bordeaux: '#7f1d1d',
    marine: '#1e3a8a', 'bleu marine': '#1e3a8a', 'bleu ciel': '#38bdf8', 'bleu nuit': '#0f172a',
    kaki: '#6b7a3a', indigo: '#4f46e5', lavande: '#c4b5fd', corail: '#ff7f50', saumon: '#fa8072',
    menthe: '#98ffcc', fuchsia: '#d946ef', magenta: '#d946ef', lime: '#84cc16', teal: '#14b8a6'
  });
  const COLOR_RE = Object.keys(COLORS).sort((a, b) => b.length - a.length).map(escRe).join('|');

  function mixHex(hex, pct) { // pct>0 éclaircit, pct<0 assombrit
    let h = String(hex).replace('#', ''); if (h.length === 3) h = h.split('').map(c => c + c).join('');
    if (h.length !== 6) return hex;
    const t = pct > 0 ? 255 : 0, p = Math.abs(pct);
    return '#' + [0, 2, 4].map(i => Math.round(parseInt(h.slice(i, i + 2), 16) * (1 - p) + t * p).toString(16).padStart(2, '0')).join('');
  }
  function withAlpha(c, a) {
    const s = String(c).trim(), h = s.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
    if (h) { let x = h[1]; if (x.length === 3) x = x.split('').map(ch => ch + ch).join(''); const [r, g, b] = [0, 2, 4].map(i => parseInt(x.slice(i, i + 2), 16)); return `rgba(${r}, ${g}, ${b}, ${a})`; }
    const m = s.match(/^rgba?\(\s*([^,]+),\s*([^,]+),\s*([^,)]+)/i);
    return m ? `rgba(${m[1].trim()}, ${m[2].trim()}, ${m[3].trim()}, ${a})` : s;
  }

  /* Trouve la couleur du fond dans le prompt (avant ou après « fond / arrière-plan ») */
  function findBackground(T) {
    const cueRe = /\b(?:fond|arrie?re[- ]plan|background)\b/g;
    const tokSrc = '(#(?:[0-9a-f]{6}|[0-9a-f]{3})\\b|rgba?\\([^)]*\\)|hsla?\\([^)]*\\)|\\b(?:' + COLOR_RE +
      ')(?:e|es|s|te|tes|he|hes)?\\b(?:\\s+(?:fonce|clair|pastel|sombre))?|\\b(?:transparent|verre|ardoise|slate|defaut|oled|sombre)\\b)';
    const STOPW = /\b(?:bordure|border|barres?|colonnes?|texte|police|ombre|halo|neon|courbe|secteurs?|legende|etiquettes?|points?|flou|blur|arrondi|coins?)\b/;
    let cm;
    while ((cm = cueRe.exec(T)) !== null) {                     // forme directe
      const from = cm.index + cm[0].length, seg = T.slice(from, from + 120);
      const t = new RegExp(tokSrc).exec(seg);
      if (t && !STOPW.test(seg.slice(0, t.index))) return { raw: t[0], start: from + t.index, end: from + t.index + t[0].length };
    }
    cueRe.lastIndex = 0;
    while ((cm = cueRe.exec(T)) !== null) {                     // forme inverse : « en rose pour le fond »
      const base = Math.max(0, cm.index - 45), seg = T.slice(base, cm.index), re = new RegExp(tokSrc, 'g');
      let last = null, t2;
      while ((t2 = re.exec(seg)) !== null) last = t2;
      if (last && /^\s*(?:(?:pour|comme|en guise de)\s+)?(?:le\s+|la\s+|l\s*['’]?\s*)?$/.test(seg.slice(last.index + last[0].length)))
        return { raw: last[0], start: base + last.index, end: base + last.index + last[0].length };
    }
    return null;
  }
  function maskBackground(T) {
    const b = findBackground(T);
    return b ? T.slice(0, b.start) + ' '.repeat(b.end - b.start) + T.slice(b.end) : T;
  }
  function resolveBgToken(raw) {
    const w = String(raw).trim();
    if (w[0] === '#' || /^(rgb|hsl)/.test(w)) return w;
    if (/^(noir|sombre|oled)/.test(w)) return 'deep_black';
    if (/^(transparent|verre)/.test(w)) return 'glass_transparent';
    if (/^(ardoise|slate|defaut)/.test(w)) return 'dark_slate';
    const parts = w.split(/\s+/);
    const mod = /^(fonce|clair|pastel|sombre)$/.test(parts[parts.length - 1]) ? parts.pop() : null;
    const name = parts.join(' ');
    let hex = COLORS[name];
    if (!hex) for (const suf of ['hes', 'he', 'es', 'tes', 'te', 's', 'e'])
      if (name.endsWith(suf) && COLORS[name.slice(0, -suf.length)]) { hex = COLORS[name.slice(0, -suf.length)]; break; }
    if (!hex) return null;
    if (mod === 'fonce' || mod === 'sombre') hex = mixHex(hex, -0.4); else if (mod) hex = mixHex(hex, 0.4);
    return hex;
  }

  const DEFAULT_PALETTE = ['#3b82f6', '#10b981', '#f97316', '#8b5cf6', '#ef4444', '#eab308', '#06b6d4', '#ec4899'];
  const SHADOWS = { none: 'none', soft: '0 6px 18px rgba(0, 0, 0, 0.45)', neon_blue: '0 0 25px rgba(59, 130, 246, 0.55)', neon_purple: '0 0 25px rgba(139, 92, 246, 0.55)' };
  const BACKGROUNDS = { dark_slate: 'rgba(17, 24, 39, 0.88)', deep_black: 'rgba(10, 10, 15, 0.94)', glass_transparent: 'rgba(255, 255, 255, 0.04)' };
  const CHART_TYPES = ['bar', 'pie', 'donut', 'line', 'scatter', 'treemap', 'card'];
  const ACTIONS = ['create', 'update', 'delete', 'list', 'show', 'chat', 'explain', 'undo', 'unknown', 'dashboard_bg', 'global_filter'];
  const PROTECTED_ACTIONS = ['dashboard_bg', 'global_filter', 'delete', 'list', 'show', 'undo', 'explain', 'chat'];
  const STOP = new Set(('le la les un une des de du d l et ou en au aux par pour sur avec sans dans ce cet cette ces mon ma mes ton ta tes je tu il nous vous veux voudrais ' +
    'cree creer moi mets mettre fais faire donne montre affiche visuel graphique chart top barre barres camembert pie donut courbe ligne scatter treemap carte kpi ' +
    'plus est sont qui que quoi tout tous toute seulement uniquement stp svp bar line card legende legendes couleur ainsi comme apres alors puis ensuite ' +
    'meilleur pire repartition pourcentage dashboard').split(' '));

  const COUNTRY_SYNONYMS = {
    'tunisia': ['tunisie', 'tnisie', 'tunis', 'tunisia', 'tounes'],
    'france': ['france', 'francais', 'française', 'fr'],
    'germany': ['allemagne', 'germany', 'deutschland', 'allemand'],
    'spain': ['espagne', 'spain', 'espagen', 'espagnol'],
    'italy': ['italie', 'italy', 'italien'],
    'turkey': ['turquie', 'turkey', 'turkie', 'turk'],
    'greece': ['grece', 'greece', 'grec'],
    'portugal': ['portugal', 'portugais'],
    'united states': ['usa', 'us', 'etats-unis', 'etats unis', 'united states', 'amerique', 'dollar'],
    'united kingdom': ['uk', 'royaume-uni', 'royaume uni', 'angleterre', 'great britain', 'gb'],
    'switzerland': ['suisse', 'switzerland', 'swiss'],
    'belgium': ['belgique', 'belgium'],
    'netherlands': ['pays-bas', 'pays bas', 'netherlands', 'hollande'],
    'morocco': ['maroc', 'morocco'],
    'algeria': ['algerie', 'algeria'],
    'egypt': ['egypte', 'egypt'],
    'japan': ['japon', 'japan'],
    'china': ['chine', 'china'],
    'brazil': ['bresil', 'brazil'],
    'russia': ['russie', 'russia'],
    'canada': ['canada'],
    'australia': ['australie', 'australia'],
    'india': ['inde', 'india'],
    'south africa': ['afrique du sud', 'south africa'],
    'saudi arabia': ['arabie saoudite', 'saudi arabia', 'saudi']
  };

  /* ── [CORRECTIF 3] matchCountryLabel sécurisé ── */
  function matchCountryLabel(word, availableLabels) {
    if (!word) return null;
    const wNorm = ascii(word).trim();
    if (wNorm.length < 2) return null;
    for (const lb of availableLabels) {
      const lbNorm = ascii(lb).trim();
      if (lbNorm === wNorm) return lb;
      if (wNorm.length >= 4 && lbNorm.length >= 4 && (lbNorm.includes(wNorm) || wNorm.includes(lbNorm))) return lb;
    }
    const synHit = (s, w) => s === w || (s.length > 3 && w.length > 3 && (w.includes(s) || s.includes(w)));
    for (const [canonical, syns] of Object.entries(COUNTRY_SYNONYMS)) {
      if (!syns.some(s => synHit(s, wNorm))) continue;
      for (const lb of availableLabels) {
        const lbNorm = ascii(lb).trim();
        if (lbNorm === canonical || syns.some(s => synHit(s, lbNorm))) return lb;
      }
    }
    let best = null, bestDist = 999;
    if (wNorm.length >= 5) {
      const maxD = wNorm.length >= 8 ? 2 : 1;
      for (const lb of availableLabels) {
        const lbNorm = ascii(lb).trim();
        const d = lev(wNorm, lbNorm);
        if (d <= maxD && d < bestDist && lbNorm.length >= 5) { bestDist = d; best = lb; }
      }
    }
    return best;
  }

  function extractEntitiesFromText(text) {
    const T = ascii(text);
    const markerMatch = T.match(/(?:filtrer?\s+(?:ce\s+visuel\s+)?(?:seulement\s+)?(?:pour|sur)?|c[' ]est\s+a\s+dire|pays\s*(?:d[' ]europe)?|seulement|uniquement)\s*[:=]?\s*(.+)/i);
    const searchStr = markerMatch ? markerMatch[1] : T;
    const words = searchStr.replace(/ect|etc|\.\.\.|\./g, '').split(/[\s,;:|]+/).map(w => w.trim()).filter(w => w.length >= 2 && !STOP.has(w));
    const cat = ensureCatalog();
    const availableLabels = [];
    cat.datasets.forEach(d => {
      (d.rows || []).forEach(r => {
        const val = String(r[d.dim] || '');
        if (val && !availableLabels.includes(val)) availableLabels.push(val);
      });
    });
    const D = root.Dashboard;
    const reg = D && D.getRegistry ? D.getRegistry() : {};
    Object.values(reg).forEach(r => {
      (r.config && r.config.data ? r.config.data : []).forEach(row => {
        const labelField = r.config.labelField;
        const val = String((labelField && row[labelField]) || row.country || row.name || row.category || Object.values(row)[0] || '');
        if (val && !availableLabels.includes(val)) availableLabels.push(val);
      });
    });
    const found = [];
    words.forEach(w => {
      const matched = matchCountryLabel(w, availableLabels);
      if (matched && !found.includes(matched)) found.push(matched);
      else if (markerMatch && w.length >= 3 && !found.includes(w) && !['visuel', 'graphique', 'carte', 'chart', 'pour', 'sur', 'dans', 'tout', 'tous', 'les', 'des', 'ces', 'couleur', 'fond', 'barres'].includes(w)) found.push(w);
    });
    return found;
  }

  let CATALOG = null;

  /* ═══════════════════════ VISUELS PERSISTANTS ═══════════════════════ */
  const Visuals = (function () {
    let items = [];
    function persist() {
      if (!CFG.persist) return;
      Store.set(CFG.storageKeyVisuals, items.map(x => ({ sid: x.sid, spec: x.spec, cfg: x.cfg, style: x.style })));
    }
    return {
      get items() { return items; },
      count: () => items.length,
      bySid: sid => items.find(x => x.sid === sid) || null,
      byId: id => items.find(x => x.id === id) || null,
      add(it) { items.push(it); persist(); },
      update(sid, patch) { const x = items.find(i => i.sid === sid); if (x) { Object.assign(x, patch); persist(); } },
      remove(sid) { items = items.filter(x => x.sid !== sid); persist(); },
      prune() {
        if (!_restoreDone) return;
        const D = root.Dashboard, reg = D && D.getRegistry ? D.getRegistry() : null;
        if (!reg) return;
        const n = items.length;
        items = items.filter(x => reg[x.id]);
        if (items.length !== n) persist();
      },
      clear() { items = []; persist(); },
      setAll(a) { items = a; },
      persist
    };
  })();

  function activeItem(intent) {
    Visuals.prune();
    const D = root.Dashboard;
    // 1. Visuel explicitement ciblé par intent (ex. identifié par titre ou ID)
    if (intent && intent.targetVisualId) {
      const it = Visuals.byId(intent.targetVisualId);
      if (it) return it;
      const reg = D && D.getRegistry ? D.getRegistry() : {};
      if (reg[intent.targetVisualId]) {
        return {
          id: intent.targetVisualId,
          sid: intent.targetSid || (reg[intent.targetVisualId].config && reg[intent.targetVisualId].config._agentSid) || intent.targetVisualId,
          legacy: true,
          spec: null,
          cfg: reg[intent.targetVisualId].config || {},
          style: reg[intent.targetVisualId].containerStyle || {}
        };
      }
    }
    if (intent && intent.targetSid) {
      const it = Visuals.bySid(intent.targetSid);
      if (it) return it;
    }
    // 2. Visuel actif cliqué dans l'UI
    const activeId = D && D.getActiveCardId ? D.getActiveCardId() : null;
    if (activeId) {
      const it = Visuals.byId(activeId);
      if (it) return it;
      const reg = D && D.getRegistry ? D.getRegistry() : {};
      if (reg[activeId]) {
        return {
          id: activeId,
          sid: (reg[activeId].config && reg[activeId].config._agentSid) || activeId,
          legacy: true,
          spec: null,
          cfg: reg[activeId].config || {},
          style: reg[activeId].containerStyle || {}
        };
      }
    }
    // 3. Dernier sid en mémoire agent
    let it = Memory.state.activeSid ? Visuals.bySid(Memory.state.activeSid) : null;
    if (it) return it;
    // 4. Dernier visuel du registre ou de la liste
    const id = D && D.getActiveOrLatestCardId ? D.getActiveOrLatestCardId() : null;
    if (id) { const item = Visuals.byId(id); return item || { id, legacy: true, spec: null }; }
    if (Visuals.count()) it = Visuals.items[Visuals.count() - 1];
    return it || null;
  }
  const activeVisualId = (intent) => { const it = activeItem(intent); return it ? it.id : null; };
  const activeSpec = (intent) => { const it = activeItem(intent); return it && it.spec ? it.spec : null; };
  const activeMeasureIds = (intent) => { const s = activeSpec(intent); return s ? s.measureIds : []; };

  /* ═══════════════════════ MÉMOIRE ═══════════════════════ */
  const Memory = (function () {
    let turns = [];
    const state = { activeSid: null, pending: null, log: [], lastAction: null };
    function save() {
      if (!CFG.persist) return;
      Store.set(CFG.storageKeyMemory, { turns: turns.slice(-CFG.memoryTurns * 2), state: { activeSid: state.activeSid, pending: state.pending, lastAction: state.lastAction }, savedAt: Date.now() });
    }
    function load() {
      const d = Store.get(CFG.storageKeyMemory); if (!d) return;
      turns = Array.isArray(d.turns) ? d.turns : [];
      if (d.state) { state.activeSid = d.state.activeSid || null; state.pending = d.state.pending || null; state.lastAction = d.state.lastAction || null; }
    }
    return {
      state, load, save,
      addTurn(role, content, meta) {
        turns.push({ role, content: String(content || ''), meta: meta || null, t: Date.now() });
        if (turns.length > CFG.memoryTurns * 2) turns = turns.slice(-CFG.memoryTurns * 2);
        save();
      },
      history(n) { return turns.slice(-(n || CFG.llmHistoryTurns) * 2).map(t => ({ role: t.role, content: t.content.slice(0, 600) })); },
      lastUserText() { for (let i = turns.length - 1; i >= 0; i--) if (turns[i].role === 'user') return turns[i].content; return ''; },
      hasContext() { return Visuals.count() > 0; },
      commit(intent, result) {
        if (intent && intent.action) state.lastAction = intent.action;
        if (result && result.sid) state.activeSid = result.sid;
        save();
      },
      setPending(p) { state.pending = p; save(); },
      clearPending() { state.pending = null; save(); },
      reset() { turns = []; Object.assign(state, { activeSid: null, pending: null, log: [] }); save(); },
      get turns() { return turns; }
    };
  })();

  /* ═══════════════════════ RAG ═══════════════════════ */
  const RAGStore = (function () {
    let _chunks = [], _idf = {}, _avgDocLen = 0, _built = false;
    const tokenize = t => ascii(String(t || '')).replace(/[^a-z0-9]+/g, ' ').trim().split(' ').filter(x => x.length >= 2);
    const tfOf = tokens => { const tf = {}; for (const t of tokens) tf[t] = (tf[t] || 0) + 1; return tf; };

    function buildIDF(chunks) {
      const df = {}; let total = 0;
      chunks.forEach(c => { total += c.tokens.length; new Set(c.tokens).forEach(t => { df[t] = (df[t] || 0) + 1; }); });
      const N = chunks.length || 1; _avgDocLen = total / N;
      const idf = {};
      Object.keys(df).forEach(t => { idf[t] = Math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5)); });
      return idf;
    }
    function semanticChunk(text, size = CFG.chunkSize, overlap = CFG.chunkOverlap) {
      const lines = String(text || '').split(/\n+/).map(l => l.trim()).filter(Boolean);
      const out = []; let cur = [];
      const commit = () => { if (cur.length) out.push(cur.join(' ')); };
      for (const line of lines) {
        const words = line.split(/\s+/).filter(Boolean);
        if (cur.length + words.length > size && cur.length) { commit(); cur = cur.slice(-overlap).concat(words); }
        else cur.push(...words);
      }
      commit();
      return out.length ? out : [String(text || '')];
    }
    function add(text, source, meta) { _chunks.push({ id: uid('chunk_'), text, tokens: tokenize(text), source, meta: meta || {} }); }

    function build(store, catalog) {
      _chunks = [];
      if (!store && !catalog) return;
      catalog = catalog || {};
      if (Array.isArray(catalog.datasets)) {
        catalog.datasets.forEach(ds => {
          if (!ds) return;
          const rows = Array.isArray(ds.rows) ? ds.rows : [];
          const measures = Array.isArray(ds.measures) ? ds.measures : [];
          const labels = [...new Set(rows.map(r => String(r[ds.dim])))].slice(0, 30);
          add([`Dataset: ${ds.key || ''}`, `Dimension: ${ds.dim || ''} (${ds.dimLabel || ''})`, `Temporelle: ${ds.dimIsTime ? 'Oui' : 'Non'}`,
          `Mesures: ${measures.map(m => `${m.label || m.name} [${m.id || ''}] (${m.kind || ''})`).join(', ')}`,
          `Valeurs: ${labels.join(', ')}`,
          `Mots clés: ${(ds.dsTerms || []).slice(0, 10).join(', ')}`, `Termes dimension: ${(ds.dimTerms || []).slice(0, 8).join(', ')}`].join('\n'),
            'dataset_schema', { datasetKey: ds.key });
          measures.forEach(m => add([`Mesure: ${m.label || m.name} (${m.id || ''})`, `Dataset: ${ds.key || ''} (axe ${ds.dimLabel || ''})`, `Nature: ${m.kind || ''}`,
          `Synonymes: ${(m.terms || []).slice(0, 8).join(', ')}`, `DAX: ${m.dax || 'SUM/AVG'}`, `SQL: ${m.sql || 'SELECT SUM/AVG'}`].join('\n'),
            'measure_meta', { measureId: m.id, label: m.label || m.name, dimLabel: ds.dimLabel, datasetKey: ds.key }));
          if (rows.length) {
            const txt = `Échantillon [${ds.key}]:\n` + rows.slice(0, 25).map(r => `${r[ds.dim]}: ` + measures.map(m => `${m.name}=${r[m.name]}`).join(', ')).join('\n');
            semanticChunk(txt).forEach((sc, i) => add(sc, 'data_sample', { datasetKey: ds.key, part: i }));
          }
        });
      }
      if (Array.isArray(catalog.summary)) {
        catalog.summary.forEach(s => {
          if (!s) return;
          add([`KPI global: ${s.label || ''} (${s.id || ''})`, `Valeur: ${(store && store.summary ? store.summary : {})[s.key] || ''}`, `Termes: ${(s.terms || []).slice(0, 8).join(', ')}`].join('\n'),
            'summary_kpi', { summaryId: s.id, label: s.label });
        });
      }
      if (Array.isArray(catalog.kpis)) {
        catalog.kpis.forEach(k => {
          if (!k) return;
          add([
            `KPI: ${k.name || ''} (${k.id || ''})`,
            `Domaine: ${k.domain || ''}`,
            `Mesure: ${k.metric_column || ''}`,
            `Dimension: ${k.dimension_column || ''}`,
            `SQL: ${k.sql_superset || ''}`,
            `DAX: ${k.dax_measure || ''}`,
            `Prompts: ${(k.suggested_prompts || []).join(', ')}`
          ].join('\n'), 'kpi_catalog_item', { kpiId: k.id });
        });
      }
      (LocalLoRA._patterns || []).forEach((p, i) => add(`Pattern appris #${i + 1}: "${p.prompt}" → ${p.action} ${p.chartType || ''} ${p.kpi || ''}`, 'lora_pattern', { prompt: p.prompt }));
      _idf = buildIDF(_chunks); _built = true;
    }
    function search(query, topK = CFG.maxChunks) {
      if (!_built || !_chunks.length) return [];
      const q = tokenize(query); if (!q.length) return [];
      const scored = [];
      for (const c of _chunks) {
        const tf = tfOf(c.tokens), len = c.tokens.length || 1; let s = 0;
        for (const t of q) if (tf[t]) {
          s += (_idf[t] || 0.1) * (tf[t] * (CFG.bm25K1 + 1)) / (tf[t] + CFG.bm25K1 * (1 - CFG.bm25B + CFG.bm25B * (len / (_avgDocLen || 1))));
        }
        if (s > 0) {
          if (c.source === 'lora_pattern') s *= 1.6; else if (c.source === 'measure_meta') s *= 1.4; else if (c.source === 'dataset_schema') s *= 1.25;
          scored.push({ chunk: c, score: s });
        }
      }
      scored.sort((a, b) => b.score - a.score);
      return scored.filter(s => s.score >= CFG.ragScoreThreshold).slice(0, topK).map(s => s.chunk);
    }
    const format = chunks => (!chunks || !chunks.length) ? '' :
      '=== [RAG] ===\n' + chunks.map((c, i) => `[${i + 1}|${c.source}] ${c.text.replace(/\n+/g, ' ')}`).join('\n') + '\n=== [FIN RAG] ===';
    return { build, search, format, get chunks() { return _chunks; }, get built() { return _built; } };
  })();

  /* ═══════════════════════ LORA ═══════════════════════ */
  const LocalLoRA = (function () {
    const KEY = 'bi_agent_lora_adapters_v5';
    let _patterns = [], _trained = false, _dataFiles = [], _adapters = {};
    function load() {
      const p = Store.get(KEY); if (!p) return;
      _patterns = p.patterns || []; _adapters = p.adapters || {}; _trained = !!p.trained;
    }
    function save() { Store.set(KEY, { patterns: _patterns.slice(-250), adapters: _adapters, trained: _trained, updatedAt: Date.now() }); }

    function record(prompt, intent, ok) {
      if (!ok || !prompt || !intent || intent.action === 'unknown' || intent.action === 'chat') return;
      const clean = String(prompt).trim();
      const ex = _patterns.find(p => p.prompt.toLowerCase() === clean.toLowerCase());
      if (ex) { ex.frequency = (ex.frequency || 1) + 1; ex.lastSeen = Date.now(); return save(); }
      const g0 = intent.groups && intent.groups[0];
      _patterns.push({ prompt: clean, action: intent.action, chartType: intent.chartType, kpi: g0 && g0.measures[0] ? g0.measures[0].id : null, topN: intent.topN, frequency: 1, createdAt: Date.now() });
      save();
    }
    async function scanFolderDataFiles() {
      if (typeof fetch === 'function') {
        try {
          const ctrl = new AbortController(); const to = setTimeout(() => ctrl.abort(), 2500);
          const r = await fetch(CFG.dataFilesApiUrl, { signal: ctrl.signal }); clearTimeout(to);
          if (r.ok) {
            const body = await r.json();
            const list = (Array.isArray(body.files) ? body.files : (body.data || [])).filter(f => CFG.dataFileExtensions.includes('.' + String(f).split('.').pop().toLowerCase()));
            if (list.length) { _dataFiles = list; return _dataFiles; }
          }
        } catch (e) { }
      }
      _dataFiles = ['pwc_clients_analysis_clean.xlsx', 'pwc_events_clean.xlsx', 'world_economics_clean.xlsx'];
      return _dataFiles;
    }
    async function finetune(custom = {}, onProgress = null) {
      const files = await scanFolderDataFiles();
      if (!files.length) return { success: false, reason: 'Aucun fichier .xls/.xlsx/.csv trouvé.' };
      const hp = Object.assign({}, CFG.loraHyperparams, custom);
      const results = []; let serverOk = 0;
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        if (onProgress) onProgress({ file, step: i + 1, total: files.length, status: 'training' });
        let done = false;
        try {
          const ctrl = new AbortController(); const timer = setTimeout(() => ctrl.abort(), 60000);
          const res = await fetch(CFG.loraServerUrl + CFG.loraEndpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: ctrl.signal, body: JSON.stringify({ file, hyperparams: hp, model: CFG.model }) });
          clearTimeout(timer);
          if (res.ok) { serverOk++; results.push({ file, success: true, mode: 'server' }); done = true; }
        } catch (e) { }
        if (!done) { _adapters[file] = { file, mode: 'pattern_memory_only' }; results.push({ file, success: false }); }
      }
      _trained = serverOk > 0; save();
      if (root.BI_DATA_STORE && CATALOG) RAGStore.build(root.BI_DATA_STORE, CATALOG);
      return { success: serverOk > 0, totalFiles: files.length, serverTrained: serverOk, hyperparamsUsed: hp, results };
    }
    function computeLoRABoost(prompt, intent) {
      if (!_patterns.length) return 0;
      const pw = new Set(normWords(prompt).trim().split(/\s+/)); let best = 0;
      for (const pat of _patterns) {
        if (pat.action !== intent.action) continue;
        const w = new Set(normWords(pat.prompt).trim().split(/\s+/));
        const inter = [...pw].filter(x => w.has(x)).length, uni = new Set([...pw, ...w]).size;
        if (uni && inter / uni > best) best = inter / uni;
      }
      return best;
    }
    load();
    return { record, finetune, scanFolderDataFiles, computeLoRABoost, get _patterns() { return _patterns; }, get trained() { return _trained; }, get dataFiles() { return _dataFiles; }, get activeAdapters() { return _adapters; } };
  })();

  /* ═══════════════════════ CATALOGUE ═══════════════════════ */
  function termsFor(name) {
    const base = String(name).replace(/([a-z])([A-Z])/g, '$1_$2').toLowerCase();
    const bare = base.replace(/^(total|avg|sum|mean|nb|num)_/, '');
    const t = new Set();
    [base, bare].forEach(k => { t.add(k.replace(/_/g, ' ')); (SYN[k] || []).forEach(a => t.add(a)); });
    bare.split('_').forEach(tok => { if (tok.length >= 3) { t.add(tok); synFor(tok).forEach(a => t.add(a)); } });
    return [...t];
  }
  const familyOf = name => String(name).replace(/([a-z])([A-Z])/g, '$1_$2').toLowerCase().replace(/^(total|avg|sum|mean|nb|num)_/, '');
  function guessKind(name) {
    const n = String(name).toLowerCase();
    if (/(event|count|nombre|volume|^nb_|_nb$|^num_)/.test(n)) return 'count';
    if (/(rate|growth|inflation|pct|percent|unemployment|roe|margin|yield|%)/.test(n)) return 'percent';
    if (/(ratio|multiple)/.test(n)) return 'ratio';
    if (/(market_?cap|revenue|ebitda|income|profit|gdp|fdi|usd|amount|debt|sales|cost|\$)/.test(n)) return 'money';
    return 'number';
  }

  function buildCatalog(ds) {
    const datasets = [], summary = [];
    const registerDs = (key, v, custom = []) => {
      if (!Array.isArray(v) || !v.length || typeof v[0] !== 'object' || v[0] === null) return;
      const sample = v[0], keys = Object.keys(sample);
      const dims = keys.filter(k => typeof sample[k] === 'string' || isTimeName(k));
      const measures = keys.filter(k => typeof sample[k] === 'number' && !isTimeName(k) && !/^(id|index|rank)$/i.test(k));
      if (!dims.length || !measures.length) return;
      dims.forEach(dim => {
        const subKey = (dims.length > 1 && dim !== dims[0]) ? `${key}_${dim}` : key;
        datasets.push({
          key: subKey, rows: v, dim, dimLabel: LABELS[dim] || humanize(dim), dimIsTime: isTimeName(dim),
          dimTerms: termsFor(dim).concat(custom), dsTerms: termsFor(key).concat(custom),
          measures: measures.map(m => ({
            id: subKey + '.' + m, name: m, label: LABELS[m] || humanize(m), kind: guessKind(m),
            terms: termsFor(m).concat(m === 'rate_usd' ? ['currency', 'devise', 'usd', 'taux', 'meilleur que usa', 'pire que usa', 'meilleur que', 'pire que'] : []),
            family: familyOf(m), dax: null, sql: null
          }))
        });
      });
    };
    Object.keys(ds || {}).forEach(key => {
      const v = ds[key];
      if (key === 'summary' && v && typeof v === 'object' && !Array.isArray(v)) {
        Object.keys(v).forEach(k => { if (typeof v[k] === 'number') summary.push({ id: 'summary.' + k, key: k, label: LABELS[k] || humanize(k), kind: guessKind(k), terms: termsFor(k), family: familyOf(k), dax: null, sql: null }); });
        return;
      }
      if (key === 'macro_economics' && v && typeof v === 'object' && !Array.isArray(v)) {
        if (Array.isArray(v.top_currencies) && v.top_currencies.length) registerDs('top_currencies', v.top_currencies, ['currency', 'currencies', 'devise', 'devises', 'taux de change', 'change', 'dollar', 'usd', 'usa', 'monnaie']);
        if (Array.isArray(v.all_countries_sample) && v.all_countries_sample.length) registerDs('macro_countries', v.all_countries_sample, ['macro', 'economie', 'inflation', 'pib', 'gdp', 'gdp_growth', 'growth', 'fdi', 'fdi_inflow', 'inflow', 'ide', 'investissements directs', 'usa', 'dollar', 'meilleur que', 'pire que', 'currency', 'devise', 'rate_usd']);
        return;
      }
      if (key === 'top_10_market_cap') return registerDs(key, v, ['company', 'companies', 'entreprise', 'entreprises', 'societe', 'societes', 'client', 'clients', 'leader', 'leaders']);
      registerDs(key, v);
    });
    return { datasets, summary, external: [] };
  }

  function mergeExternalCatalog(cat, json) {
    const items = Array.isArray(json) ? json : (json && (json.kpis || json.measures || json.catalog)) || [];
    if (!Array.isArray(items)) return 0;
    const all = []; cat.datasets.forEach(d => d.measures.forEach(m => all.push(m))); cat.summary.forEach(s => all.push(s));
    let merged = 0;
    items.forEach(it => {
      if (!it || typeof it !== 'object') return;
      const aRaw = it.aliases || it.synonyms || it.keywords || [];
      const aliases = Array.isArray(aRaw) ? aRaw : String(aRaw).split(',');
      const text = normWords([it.id, it.name, it.label, it.title, it.kpi, it.description].concat(aliases).filter(Boolean).join(' '));
      let best = null, bs = 0;
      all.forEach(e => { const sc = e.terms.filter(t => has(text, t)).length; if (sc > bs) { bs = sc; best = e; } });
      cat.external.push({ id: it.id || it.name || it.label, label: it.label || it.name || it.title || it.id, description: it.description || '' });
      if (best && bs >= 1) {
        const dax = it.dax || it.DAX || it.dax_formula, sql = it.sql || it.SQL || it.sql_query;
        if (dax) best.dax = dax; if (sql) best.sql = sql;
        aliases.map(a => String(a).trim()).filter(Boolean).forEach(a => { if (best.terms.indexOf(a) === -1) best.terms.push(a); });
        merged++;
      }
    });
    return merged;
  }
  function ensureCatalog() {
    if (!CATALOG) { CATALOG = buildCatalog(root.BI_DATA_STORE); if (!RAGStore.built) RAGStore.build(root.BI_DATA_STORE, CATALOG); }
    return CATALOG;
  }
  function findById(id) {
    const cat = ensureCatalog(); if (typeof id !== 'string') return null;
    const s = cat.summary.find(x => x.id === id); if (s) return { kind: 'summary', item: s };
    for (const d of cat.datasets) { const m = d.measures.find(x => x.id === id); if (m) return { kind: 'dataset', ds: d, measure: m }; }
    return null;
  }
  function groupsFromIds(ids) {
    const byDs = new Map(), groups = [];
    (ids || []).forEach(id => {
      const f = findById(id); if (!f) return;
      if (f.kind === 'summary') return groups.push({ kind: 'summary', item: f.item, measures: [f.item], score: 5 });
      if (!byDs.has(f.ds.key)) { const g = { kind: 'dataset', ds: f.ds, measures: [], score: 5 }; byDs.set(f.ds.key, g); groups.push(g); }
      const g = byDs.get(f.ds.key); if (!g.measures.includes(f.measure)) g.measures.push(f.measure);
    });
    return groups;
  }
  const measureLabel = (m, ds) => m.label + (ds ? ' par ' + ds.dimLabel : '');

  /* ═══════════════════════ PARSING PAR RÈGLES ═══════════════════════ */
  function matchKPIs(P, T, cardCue, legendP) {
    const cat = ensureCatalog();
    const totalCue = /(total|global|cumule|somme|moyen|combien|indicateur)/.test(T);
    const cands = [];
    cat.datasets.forEach((d, order) => {
      const isMacro = d.key === 'macro_countries';
      const isTopCur = d.key === 'top_currencies';
      const baselineCue = /\b(meilleur|pire|plus (forte?|faible)|usa?|dollar|currency|devise|france|tunisie|japon|chine|allemagne)\b/.test(T);
      const macroBoost = (isMacro && baselineCue) ? 2.5 : 0;
      const topCurPenalty = (isTopCur && baselineCue) ? -2.5 : 0;
      const dimHits = d.dimTerms.filter(t => has(P, t)).length + (legendP ? d.dimTerms.filter(t => has(legendP, t)).length * 2 : 0);
      const dsHits = d.dsTerms.filter(t => has(P, t)).length;
      const measHit = d.measures.filter(m => m.terms.some(t => has(P, t)));
      const measHits = measHit.reduce((a, m) => a + m.terms.filter(t => has(P, t)).length, 0);
      const base = (dimHits > 0 ? 3.5 * dimHits : 0) + dsHits * 1.5 + macroBoost + topCurPenalty;
      let measures = measHit;
      if (measures.length > 1 && measures.some(m => m.name === 'gdp_growth') && measures.some(m => m.name === 'gdp') && /(growth|croissance)/.test(T)) measures = measures.filter(m => m.name !== 'gdp');
      if (!measures.length && base >= 2) measures = [d.measures[0]];
      if (!measures.length) return;
      cands.push({ kind: 'dataset', ds: d, measures, score: base + measHits * 3, dimHit: dimHits > 0, order, dimOnly: measHit.length === 0 });
    });
    cat.summary.forEach((s, i) => {
      if (!s.terms.some(t => has(P, t))) return;
      cands.push({ kind: 'summary', item: s, measures: [s], score: 3 + (cardCue ? 1.5 : 0) + (totalCue ? 1.5 : 0), dimHit: false, order: 1000 + i });
    });
    if (!cands.length) return { groups: [], bestScore: 0, ambiguous: false };
    const pref = cardCue || totalCue;
    cands.sort((a, b) => (b.score - a.score) || ((pref ? (b.kind === 'summary') - (a.kind === 'summary') : (a.kind === 'summary') - (b.kind === 'summary'))) || (a.order - b.order));
    const best = cands[0];
    if (best.score < 2.5) return { groups: [], bestScore: best.score, ambiguous: false };
    const used = new Set(), groups = [];
    for (const c of cands) {
      if (c.score < Math.max(2.5, best.score * 0.8)) break;
      const fams = c.measures.map(m => m.family);
      if (fams.some(f => used.has(f))) continue;
      fams.forEach(f => used.add(f)); groups.push(c);
    }
    const second = cands[1];
    const ambiguous = !!second && second.score === best.score && !best.dimHit && !second.dimHit && best.measures.some(m => second.measures.some(n => n.family === m.family));
    return { groups, bestScore: best.score, ambiguous };
  }

  function parseNum(str, suffix) {
    let n = parseFloat(String(str).replace(',', '.')); if (!isFinite(n)) return undefined;
    const s = suffix || '';
    if (/^(k|mille)$/.test(s)) n *= 1e3; else if (/^(m|million|millions)$/.test(s)) n *= 1e6; else if (/^(md|milliard|milliards)$/.test(s)) n *= 1e9;
    return n;
  }

  function parseColors(T) {
    const masked = maskBackground(T)
      .replace(/\b(?:bleu|violet|mauve|blue|purple)\s+(?:neon|nean|neons)\b/gi, m => ' '.repeat(m.length))
      .replace(/(?:halo|halon|ombre|shadow)?\s*(?:neon|nean|néean|neons)\s+\w+/gi, m => ' '.repeat(m.length))
      .replace(/(?:fond|arriere[- ]plan|background)\s+(?:\w+\s+)?(?:noir|sombre|transparent|verre|\w+)/gi, m => ' '.repeat(m.length))
      .replace(/(?:bordure|border)\s+(?:\w+\s+){0,2}(?:noir|blanc|rouge|bleu|vert|\w+)/gi, m => ' '.repeat(m.length));
    const mentions = [];
    const re = new RegExp('(#(?:[0-9a-f]{6}|[0-9a-f]{3})\\b)|\\b(' + COLOR_RE + ')(?:e|es|s|te|tes|he|hes)?\\b', 'g');
    let m;
    while ((m = re.exec(masked)) !== null) mentions.push({ hex: m[1] || COLORS[m[2]], idx: m.index });
    const list = []; mentions.forEach(x => { if (list.indexOf(x.hex) === -1) list.push(x.hex); });
    return { list, mentions };
  }

  function parseFormat(T) {
    const f = {};
    const numRe = '(-?\\d+(?:[.,]\\d+)?)\\s*(k|md|milliards?|millions?|mille|m)?\\b';
    const cl = parseColors(T);
    if (cl.list.length) { f.barColor = cl.list[0]; if (cl.list.length > 1) f.palette = cl.list; }

    // ── Fond / arrière-plan : N'IMPORTE QUELLE couleur ──
    const bgFound = findBackground(T);
    if (bgFound) { const v = resolveBgToken(bgFound.raw); if (v) f.background = v; }
    else if (/(deep black|noir profond)/.test(T)) f.background = 'deep_black';
    else if (/(glassmorphism transparent|fond verre|fond transparent)/.test(T)) f.background = 'glass_transparent';
    else if (/(gris ardoise|ardoise fume|dark slate)/.test(T)) f.background = 'dark_slate';

    // opacité / transparence du fond (rend le flou visible sur un fond coloré)
    const op = T.match(/(opacite|transparence)\s*(?:du\s+fond)?\s*(?:de|d|=|:|a)?\s*(\d{1,3})\s*(?:%|pour\s*cent)/);
    if (op) { const v = Math.min(100, +op[2]) / 100; f.bgOpacity = +(op[1] === 'opacite' ? v : 1 - v).toFixed(2); }

    if (f.background && f.barColor && f.barColor.toLowerCase() === f.background.toLowerCase() && !/(?:barres?|colonnes?|secteurs?|courbe|points?)\s*(?:en\s+|de\s+)?#/i.test(T)) {
      delete f.barColor;
      if (f.palette && f.palette.length === 1) delete f.palette;
    }

    // ── Bordure de visuel (épaisseur par pixel & couleur) ──
    if (/(?:sans\s+bordure|pas\s+de\s+bordure|enleve\s+(?:la\s+)?bordure|retire\s+(?:la\s+)?bordure|supprime\s+(?:la\s+)?bordure|bordure\s*(?:=|:)?\s*0(?:\s*px)?)/i.test(T)) {
      f.borderWidth = 0;
      f.borderColor = 'transparent';
    } else {
      const bThick = T.match(/(?:(?:epaisseur|taille)\s+(?:de\s+)?(?:la\s+)?bordure|bordure|border)\s*(?:de|d|=|:|a|\s)?\s*(\d+)(?:\s*px)?/i);
      if (bThick) {
        f.borderWidth = Math.min(25, Math.max(0, parseInt(bThick[1], 10)));
      }
      const bColHex = T.match(/bordure[^#\n\r]{0,35}(#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b)/i)
        || T.match(/(#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b)[^#\n\r]{0,25}pour\s+(?:la\s+)?bordure/i);
      if (bColHex) {
        f.borderColor = bColHex[1];
      } else {
        const bColNamed = T.match(/bordure(?:\s+\w+){0,3}?\s*(?:en\s+|de\s+couleur\s+)?(rouge|bleu|vert|jaune|blanc|violet|orange|cyan|noir)/i);
        if (bColNamed && COLORS[bColNamed[1].toLowerCase()]) {
          f.borderColor = COLORS[bColNamed[1].toLowerCase()];
        }
      }
    }

    // ── Étiquettes de données (labels sur les barres/secteurs) ──
    const labelPos = /(etiquette|\blabels?\b|valeurs? (?:sur|au[- ]dessus|affichees?)|donnees? affichees?|annotation|chiffres? sur|nombres? sur|pourcentage sur)/.test(T);
    if (labelPos) {
      const neg = /(masque|cache|retire|supprime|enleve|sans|desactive|pas de|n affiche pas|ne pas afficher)/.test(T);
      f.dataLabels = !neg;
      if (!neg) {
        f.labelPosition = (/(interieur|inside|dedans|\binner\b)/.test(T)) ? 'inside' : 'outside';
      } else {
        f.labelPosition = 'none';
      }
      if (/(pourcentage uniquement|seulement le pourcentage|en pourcentage|\bpercent\b|\bpct\b)/.test(T)) f.labelFormat = 'percent_only';
      else if (/(valeur et pourcentage|les deux|both|valeur \+ pourcent)/.test(T)) f.labelFormat = 'both';
      else if (/(valeur (?:brute )?uniquement|seulement la valeur)/.test(T)) f.labelFormat = 'value_only';
    } else if (/(exterieur|outside|dehors)/.test(T)) {
      f.labelPosition = 'outside'; f.dataLabels = true;
    } else if (/(interieur|inside|dedans)/.test(T) && !/(donut|anneau|treemap)/.test(T)) {
      f.labelPosition = 'inside'; f.dataLabels = true;
    }

    // ── Légende ──
    if (/(sans legende|masque (?:la )?legende|cache (?:la )?legende|pas de legende|retire (?:la )?legende|supprime (?:la )?legende)/.test(T)) f.legend = false;
    else if (/(avec (?:la |une )?legende|affiche (?:la )?legende|montre (?:la )?legende|legende visible|afficher la legende)/.test(T)) f.legend = true;
    const lp = T.match(/legende\s+(?:en\s+|a\s+)?(haut|bas|gauche|droite|top|bottom|left|right)/);
    if (lp) {
      const pos = { haut: 'top', top: 'top', bas: 'bottom', bottom: 'bottom', gauche: 'left', left: 'left', droite: 'right', right: 'right' };
      f.legendPosition = pos[lp[1]] || lp[1]; f.legend = true;
    }

    // ── Axe Y — min/max/pas (avec ou sans le mot "axe") ──
    if (/(axe\s+y\s+auto|r(?:e|e)initialise\s+(?:l')?axe|echelle\s+auto(?:matique)?)/.test(T)) { f.yMin = null; f.yMax = null; f.yInterval = null; }
    if (/\bmin(?:imum)?\s*:\s*auto\b|\bmin\s+auto\b/.test(T)) f.yMin = null;
    if (/\bmax(?:imum)?\s*:\s*auto\b|\bmax\s+auto\b/.test(T)) f.yMax = null;
    if (/\b(?:pas|intervalle?|saut)\s*:\s*auto\b|\b(?:pas|intervalle?)\s+auto\b/.test(T)) f.yInterval = null;

    const yMin = T.match(/\b(?:min(?:imum|imal|i)?|valeur\s+min|limite\s+(?:inf(?:erieure)?))\s*(?:de|d|=|:|a|est|fixe\s+(?:a|au))?\s*(-?\d+(?:[.,]\d+)?)/);
    if (yMin && !/\bmin(?:imum)?\s*:\s*auto\b|\bmin\s+auto\b/.test(T)) f.yMin = parseFloat(yMin[1].replace(',', '.'));
    const yMax = T.match(/\b(?:max(?:imum|imal|i)?|valeur\s+max|limite\s+(?:sup(?:erieure)?)|jusqu(?:es?)?\s+a)\s*(?:de|d|=|:|a|est|fixe\s+(?:a|au))?\s*(-?\d+(?:[.,]\d+)?)/);
    if (yMax && !/\bmax(?:imum)?\s*:\s*auto\b|\bmax\s+auto\b/.test(T)) f.yMax = parseFloat(yMax[1].replace(',', '.'));
    const yStep = T.match(/\b(?:pas|intervalle|interval|step|graduation|echelon|saut)\s*(?:de|d|=|:|est)?\s*(-?\d+(?:[.,]\d+)?)/);
    if (yStep && !/\b(?:pas|intervalle?|saut)\s*:\s*auto\b|\b(?:pas|intervalle?)\s+auto\b/.test(T)) f.yInterval = parseFloat(yStep[1].replace(',', '.'));

    // ── Flou (0 à 35px) ──
    let m2 = T.match(/(?:degre\s+de\s+flou|flou|blur|glassmorphism)\s*(?:de|d|=|:|a|\|)?\s*(\d+)(?:\s*px)?/)
      || T.match(/(\d+)\s*(?:px)?\s*de\s*(?:flou|blur)/);
    if (m2) f.blur = Math.min(35, Math.max(0, parseInt(m2[1], 10)));
    else if (/sans flou|pas de flou|enleve\s+(?:le\s+)?flou|retire\s+(?:le\s+)?flou/.test(T)) f.blur = 0;
    else if (/(?:beaucoup|tres|maximum|max)\s+(?:de\s+)?flou|flou\s+(?:maximum|max|fort|eleve)/.test(T)) f.blur = 30;
    else if (/(?:un peu|leger|legerement)\s+(?:de\s+)?flou|flou\s+leger/.test(T)) f.blur = 6;
    else if (/ajoute\s+(?:le\s+|un\s+)?flou|active\s+(?:le\s+)?flou|avec\s+(?:du\s+)?flou/.test(T)) f.blur = 12;

    // ── Coins arrondis (0 à 35px) ──
    m2 = T.match(/(?:coins?\s+arrondis?|bords?\s+arrondis?|arrondi|rayon|radius|border[- ]?radius)\s*(?:de|d|=|:|a)?\s*(\d+)(?:\s*px)?/)
      || T.match(/(\d+)\s*(?:px)?\s*de\s*(?:coins?\s+arrondis?|arrondi|rayon|radius)/);
    if (m2) f.radius = Math.min(35, Math.max(0, parseInt(m2[1], 10)));
    else if (/coins?\s+(?:droits?|non arrondis?|sans arrondi)|sans\s+(?:rayon|radius|arrondi)/.test(T)) f.radius = 0;
    else if (/(?:tres|bien|fortement)\s+(?:arrondis?|ronds?)|coins?\s+tres\s+(?:arrondis?|ronds?)/.test(T)) f.radius = 28;
    else if (/(?:legerement|un peu)\s+arrondis?/.test(T)) f.radius = 8;
    else if (/coins?\s+(?:ronds?|arrondis?)\b/.test(T)) f.radius = 20;

    // ── Ombre portée / Halo ──
    if (/(sans ombre|pas d(?:e|') ombre|aucune ombre|sans halo|pas de halo|retire\s+(?:l')?(?:ombre|halo)|enleve\s+(?:l')?(?:ombre|halo))/.test(T)) f.shadow = 'none';
    else if (/(?:neon|nean|néean|halo|halon)\s*(?:bleu|blue)|neon_blue/.test(T)) f.shadow = 'neon_blue';
    else if (/(?:neon|nean|néean|halo|halon)\s*(?:violet|purple|mauve|viloet)|(?:violet|purple|mauve)\s+neon|neon_purple/.test(T)) f.shadow = 'neon_purple';
    else if (/(?:neon|nean|néean)/.test(T)) f.shadow = 'neon_blue';
    else if (/\b(avec\s+)?(?:ombres?|halos?)(?:\s+portee)?\b|shadow|ombre\s+subtile|ombre\s+power/.test(T)) f.shadow = 'soft';

    // ── Orientation des barres ──
    if (/\bbar(?:res?)?\s*(?:en\s+)?horizontale?s?\b|horizontal(?:ement)?|orienta(?:tion)?\s+horizontale?/.test(T)) f.horizontal = true;
    else if (/\bbar(?:res?)?\s*(?:en\s+)?verticale?s?\b|vertical(?:ement)?|orienta(?:tion)?\s+verticale?/.test(T)) f.horizontal = false;

    return f;
  }

  function expandAbbreviations(text) {
    return String(text)
      .replace(/\bCA\b/g, "chiffre d'affaires").replace(/\b(le|du|de|des|mon|notre)\s+ca\b/gi, "$1 chiffre d'affaires").replace(/\b([ld])'ca\b/gi, "$1 chiffre d'affaires")
      .replace(/\bmeuilleurs?\b/gi, 'meilleur').replace(/\baavec\b/gi, 'avec').replace(/\bvisuele?s?\b/gi, 'visuel')
      .replace(/\bau\s+lei\s+de\b/gi, 'au lieu de').replace(/\btour\s+les\s+visuels\b/gi, 'tous les visuels')
      .replace(/\barri[eèê]?re?\s+plan\b/gi, 'arriere-plan').replace(/\barrire\b/gi, 'arriere')
      .replace(/\bchnager?\b/gi, 'changer').replace(/\bchnage\b/gi, 'change').replace(/\bdees\b/gi, 'des').replace(/\bdu\s+toute?\s+la\b/gi, 'de toute la')
      .replace(/\btnisie\b/gi, 'tunisie').replace(/\bespagen\b/gi, 'espagne').replace(/\bturkie\b/gi, 'turquie')
      .replace(/\bviloet\b/gi, 'violet').replace(/\bnean\b/gi, 'neon').replace(/\bneean\b/gi, 'neon').replace(/\bhalon\b/gi, 'halo')
      .replace(/\bte\s+pays\s+pire\b/gi, 'et pays pire')
      .replace(/\bgdp\s+growth\b/gi, 'gdp_growth').replace(/\bcroissance\s+(?:du\s+)?pib\b/gi, 'gdp_growth')
      .replace(/\bfdi\s+inflows?\b/gi, 'fdi_inflow').replace(/\bfdi\b/gi, 'fdi_inflow').replace(/\bflux\s+ide\b/gi, 'fdi_inflow').replace(/\binvestissements?\s+directs?\b/gi, 'fdi_inflow')
      .replace(/\bcompanies\b/gi, 'entreprises').replace(/\bcompany\b/gi, 'entreprise').replace(/\bcountries\b/gi, 'pays').replace(/\bcountry\b/gi, 'pays')
      .replace(/\bnet\s+income\b/gi, 'resultat net').replace(/\bcurrencies\b/gi, 'devises').replace(/\bcurrency\b/gi, 'devise');
  }

  /* ── [CORRECTIF 2] Fautes de frappe corrigées dans le texte analysé ── */
  function normalizeTypos(text) {
    return String(text)
      .replace(/\bmeu?illeu?re?s?\b/gi, 'meilleur')
      .replace(/\bpyre\b/gi, 'pire').replace(/\brouje\b/gi, 'rouge')
      .replace(/\bchnager?\b/gi, m => /r$/i.test(m) ? 'changer' : 'change')
      .replace(/\b(?:dashbord|dashbaord|dashboar|dasboard|dashbored)\b/gi, 'dashboard')
      .replace(/\b(?:visul|viusel|visuele|visuelle)(s?)\b/gi, 'visuel$1')
      .replace(/\b(?:couluer|coleur|couleure|coulour)s?\b/gi, 'couleur')
      .replace(/\barri[eèê]?re?[\s-]+plan\b/gi, 'arriere-plan')
      .replace(/\bdees\b/gi, 'des').replace(/\btout les\b/gi, 'tous les').replace(/\bdu toute\b/gi, 'de toute')
      .replace(/\btnisie\b/gi, 'tunisie').replace(/\bespagen\b/gi, 'espagne').replace(/\bturkie\b/gi, 'turquie');
  }

  function smallTalk(T) {
    if (/^(bonjour|salut|hello|hey|bonsoir|coucou)\b/.test(T)) return "Bonjour ! 👋 Je suis ton assistant BI. Dis-moi quel indicateur tu veux voir (ex. « top 5 pays par PIB en barres ») et on construit le tableau de bord ensemble, étape par étape.";
    if (/\b(merci|thanks)\b/.test(T) && !/\d/.test(T)) return "Avec plaisir ! 😊 Tu veux ajuster ce visuel (couleur, top N, type de graphique) ou en créer un autre ?";
    if (/(qui es tu|tu es qui|que sais tu faire|tu peux faire quoi|comment ca marche|aide moi|\bhelp\b)/.test(T)) return "Je transforme ta demande en SQL Apache Superset et je crée le visuel : barres, camembert, courbe… Je peux le modifier (« top 7 au lieu de top 5 », « en rouge », « légende : France, Tunisie »), expliquer le SQL, annuler, et je me souviens de toute la conversation. Demande « quels KPI sont disponibles ? » pour la liste.";
    return null;
  }

  function stripReplaced(T) {
    const chart = '(?:camembert|pie|barres?|bar|histogramme|courbe|ligne|line|donut|anneau|treemap|nuage de points|scatter|carte)';
    return T
      .replace(/(?:au lieu d[eu']?|a la place d[eu']?|plutot que|et non)\s*(?:le\s+|la\s+|un\s+|une\s+)?(?:top\s*)?\d+/g, ' ')
      .replace(new RegExp('(?:au lieu d[eu\']?|a la place d[eu\']?|plutot que|et non)\\s*(?:le\\s+|la\\s+|un\\s+|une\\s+|du\\s+)?' + chart + '\\b', 'g'), ' ')
      .replace(new RegExp('\\bde\\s+' + chart + '\\s+(?=en\\b|a\\b|vers\\b)', 'g'), ' ');
  }

  /* ── Extraction du baseline générique ── */
  function findRateField(row) {
    if (!row || typeof row !== 'object') return null;
    const keys = Object.keys(row);
    return keys.find(k => /rate_usd|exchange_rate|rate/i.test(k) && typeof row[k] === 'number') || null;
  }

  function extractBaseline(T) {
    const cat = ensureCatalog();
    const candidates = [];
    const words = T.split(/[\s,;:.]+/).map(w => ascii(w).replace(/[^a-z0-9]/g, '')).filter(w => w.length >= 3 && !STOP.has(w));
    cat.datasets.forEach(d => {
      if (!/country|pays|nation/i.test(d.dim) && !d.dimTerms.some(t => /\bpays\b|\bcountry\b/.test(t))) return;
      const labels = [...new Set(d.rows.map(r => String(r[d.dim])))];
      labels.forEach(lb => {
        const a = ascii(lb).trim();
        if (a.length < 3) return;
        if (new RegExp('(?:^|[^a-z0-9])' + escRe(a) + '(?:$|[^a-z0-9])').test(T)) {
          candidates.push({ dsKey: d.key, label: lb, dim: d.dim, row: d.rows.find(r => String(r[d.dim]) === lb) });
        }
      });
      for (const w of words) {
        const matchedLb = matchCountryLabel(w, labels);
        if (matchedLb && !candidates.some(c => c.label === matchedLb)) {
          const r = d.rows.find(row => String(row[d.dim]) === matchedLb);
          if (r) candidates.push({ dsKey: d.key, label: matchedLb, dim: d.dim, row: r });
        }
      }
    });
    candidates.sort((a, b) => (b.dsKey === 'macro_countries' || b.dsKey === 'COUNTRY_ECONOMICS') - (a.dsKey === 'macro_countries' || a.dsKey === 'COUNTRY_ECONOMICS'));

    if (candidates.length) {
      const best = candidates[0];
      const rateField = findRateField(best.row);
      if (rateField !== null) {
        return {
          countryLabel: best.label,
          rate: Number(best.row[rateField]),
          rateField,
          isUsd: /^(usa?|etats[- ]unis|united states|usd|dollar)/i.test(best.label),
          matchedRow: best.row
        };
      }
      // Pas de rate_usd → fallback PIB
      const gdpField = Object.keys(best.row).find(k => /^gdp$/i.test(k));
      if (gdpField && typeof best.row[gdpField] === 'number') {
        return {
          countryLabel: best.label,
          rate: Number(best.row[gdpField]),
          rateField: gdpField,
          isUsd: false,
          matchedRow: best.row,
          fallback: 'gdp'
        };
      }
    }

    // 2) Pas de pays → si USA/dollar, baseline = USD rate 1
    if (/\b(usa?|etats[- ]unis|united states|usd|dollar|americain|amerique)\b/.test(T)) {
      return { countryLabel: 'USA', rate: 1, rateField: 'rate_usd', isUsd: true, matchedRow: null };
    }

    // 3) Si une devise explicite est citée, cherche son taux dans top_currencies
    const curMatch = T.match(/\b(eur|gbp|jpy|chf|cad|aud|kwd|bhd|omr|jod|tnd|mad|dzd|egp|sar|aed|qar|usd)\b/);
    if (curMatch) {
      const code = curMatch[1].toUpperCase();
      const tc = cat.datasets.find(d => d.key === 'top_currencies');
      if (tc) {
        const row = tc.rows.find(r => String(r.currency || '').toUpperCase() === code);
        if (row && row.rate_usd != null) {
          return { countryLabel: code, rate: Number(row.rate_usd), rateField: 'rate_usd', isUsd: code === 'USD', matchedRow: row };
        }
      }
    }
    return null;
  }

  /* ── [CORRECTIF 4] Détection de comparaison binaire générique (avec côté & couleur) ── */
  const BETTER_RE = /(meilleur|plus (?:forte?s?|grande?s?|grands?|hauts?|elevee?s?)|au[- ]dessus|superieur|vaut plus|>)/;
  const WORSE_RE = /(pire|moins (?:forte?s?|grande?s?|grands?|bas|bon|elevee?s?)|plus faibles?|au[- ]dessous|inferieur|en dessous|vaut moins|<)/;

  function detectComparisonSplit(intent) {
    const T = intent.textAscii || ascii(intent.text);
    const betterCue = BETTER_RE.test(T), worseCue = WORSE_RE.test(T);
    if (!betterCue && !worseCue) return null;
    const baseline = extractBaseline(T);
    if (!baseline) return null;
    const side = (betterCue && worseCue) ? 'both' : (betterCue ? 'better' : 'worse');
    const parsed = parseColors(T);
    let cb = null, cw = null;
    if (side === 'better') cb = parsed.list[0] || null;
    else if (side === 'worse') cw = parsed.list[0] || null;
    else {
      const bPos = T.search(BETTER_RE), wPos = T.search(WORSE_RE);
      parsed.mentions.forEach(mn => {
        if (Math.abs(mn.idx - bPos) <= Math.abs(mn.idx - wPos)) { if (!cb) cb = mn.hex; }
        else if (!cw) cw = mn.hex;
      });
    }
    const refLabel = baseline.countryLabel || 'USA';
    return {
      type: baseline.fallback === 'gdp' ? 'gdp_vs_baseline' : 'rate_vs_baseline',
      baseline: refLabel, baselineRate: baseline.rate, rateField: baseline.rateField || 'rate_usd',
      betterLabel: 'Meilleur que ' + refLabel, worseLabel: 'Pire que ' + refLabel,
      colorBetter: cb || '#ef4444', colorWorse: cw || '#eab308',
      explicitBetter: !!cb, explicitWorse: !!cw, side,
      threshold: baseline.rate, fallback: baseline.fallback || null,
      partialCue: side !== 'both'
    };
  }

  const GLOBAL_SCOPE_RE = /\btou[ts]?e?s?\s+(?:les|mes|ces|vos)\s+(?:visuels?|graphiques?|charts?|cartes?)\b|\bchaque\s+(?:visuel|graphique)\b|\bl['’ ]?ensemble\s+des\s+(?:visuels?|graphiques?)\b|\bpartout\b/;

  function ruleParse(text) {
    const T = ascii(normalizeTypos(text)), T2 = stripReplaced(T), P = normWords(expandAbbreviations(normalizeTypos(text)));
    const intent = {
      text, textAscii: T, action: 'unknown', chartType: null, chartExplicit: false, groups: [], topN: null, clearTop: false, sort: null, title: null,
      format: {}, colorMentions: [], legendFragment: null, filterCue: false, notes: [], confident: false, bestScore: 0, ambiguous: false,
      comparison: null
    };
    const cues = [
      ['card', /(carte kpi|kpi card|\bcard\b|indicateur|chiffre cle|valeur unique|tuile)/],
      ['donut', /(donut|anneau|beignet)/],
      ['pie', /(camembert|\bpie\b|diagramme circulaire|secteurs? circulaires?)/],
      ['scatter', /(nuage de points|scatter|dispersion|correlation|relation entre)/],
      ['treemap', /(treemap|arborescen|mosaique)/],
      ['line', /(courbe|\bligne\b|line chart|graphique en ligne|\bline\b)/],
      ['bar', /(barre|histogramme|\bbar\b|bar chart)/]
    ];
    const hasComparisonContext = /(meilleur|pire|plus (forte?|faible)|au[- ]dessus|au[- ]dessous)/.test(T2);
    for (const [type, re] of cues) {
      if (type === 'scatter' && hasComparisonContext) continue;
      if (re.test(T2)) { intent.chartType = type; intent.chartExplicit = true; break; }
    }
    const cardCue = intent.chartType === 'card';

    let m = T2.match(/(?:passe|change|remplace|monte|descends?|augmente|reduis|mets?)[^0-9]{0,25}(\d+)\s*(?:par|en|a|vers)\s*(?:top\s*)?(\d+)\b/);
    if (m) intent.topN = parseInt(m[2], 10);
    else {
      m = T2.match(/\btop\s*(\d+)\b/) || T2.match(/\b(\d+)\s*(?:premiers?|principaux|meilleurs?|plus\s+gros|plus\s+grands?|derniers?|pays|entreprises?|societes?|companies?|secteurs?|devises?|annees?)\b/) ||
        T2.match(/\b(?:meilleurs?|premiers?|top|plus\s+grands?|plus\s+gros)\s*(\d+)\b/) ||
        T2.match(/(?:je veux|mets?|passe|garde|prends?|affiche|montre|donne|limite(?: a)?)(?:\s+moi)?\s+(?:les?\s+)?(?:top\s*)?(\d+)\b/);
      if (m) intent.topN = parseInt(m[1], 10);
    }
    if (intent.topN !== null && !(intent.topN > 0)) intent.topN = null;
    if (intent.topN === null && /(sans (?:le )?(?:top|limite)|(?:enleve|retire|supprime|annule) (?:le )?(?:top|limite)|\btous\s+les\b|\btoutes\s+les\b|affiche tout|montre tout)/.test(T)) intent.clearTop = true;
    if (/(plus (faibles?|petits?|bas)|moins|bottom|pire|ordre croissant)/.test(T)) intent.sort = 'asc';
    else if (/(plus (grands?|gros|eleves?|hauts?)|ordre decroissant|meilleurs?)/.test(T)) intent.sort = 'desc';
    const tm = String(text).match(/["«"](.+?)["»"]/); if (tm) intent.title = tm[1].trim();

    if (!/(sans|masque|cache|pas de|retire|supprime)\s+(?:la\s+)?legende/.test(T)) {
      const lg = T.match(/\blegendes?\b\s*(?:est|sont|=|:|avec|en|sera|seront)?\s*(?:les?|la|l'|des?|du|d')?\s*([a-z0-9_'\- ,]{2,60})/);
      if (lg) {
        const frag = lg[1].trim();
        if (!/^(et|ou|visible|haut|bas|gauche|droite|en (haut|bas)|a (gauche|droite))\b/.test(frag)) intent.legendFragment = frag;
      }
    }
    intent.filterCue = /\b(pour|uniquement|seulement|only|entre|parmi|compare|comparer|versus|contre)\b/.test(T);
    // Extrait filterValues si le prompt demande de filtrer UN visuel (pas global) sur des pays/valeurs
    if (intent.filterCue && /(filtrer?|seulement|uniquement|c est a dire|pays d|ce visuel|sur ce)/.test(T)) {
      intent.filterValues = extractEntitiesFromText(text);
    }

    intent.format = parseFormat(T);
    intent.colorMentions = parseColors(T).mentions;
    if (intent.legendFragment && intent.colorMentions.length &&
      /(couleur|colore|colorie|teinte|\ben\s+(?:rouge|bleu|vert|jaune|orange|violet|rose|cyan|gris|noir|blanc)\b|#[0-9a-f]{3,6})/.test(intent.legendFragment))
      intent.legendFragment = null;
    if (intent.colorMentions.length && !/(seulement|uniquement|only|filtr|garde|parmi|entre)/.test(T)) {
      intent.filterCue = false; intent.filterValues = undefined;
    }
    const hasFormat = Object.keys(intent.format).length > 0;

    // ── Comparaison binaire générique ──
    intent.comparison = detectComparisonSplit(intent);

    const legendP = intent.legendFragment ? normWords(intent.legendFragment) : null;
    const match = matchKPIs(P, T, cardCue, legendP);
    intent.groups = match.groups; intent.bestScore = match.bestScore; intent.ambiguous = match.ambiguous;
    if (match.ambiguous) intent.notes.push("Plusieurs datasets contiennent ce KPI — précise « par secteur » ou « par année ».");
    if ((/(^|\s)(?:un|dans un|ce|le)\s+(?:visuel|graphique|chart|pie|donut|carte)\b/.test(T) || intent.chartType === 'pie') && intent.groups.length > 1) intent.groups = intent.groups.slice(0, 1);

    // ── Changement d'arrière-plan de TOUT le dashboard ──
    const isDashboardMention = /(?:toute?\s+(?:la\s+|le\s+)?dashboard|tableau\s+de\s+bord|de\s+la\s+dashboard|du\s+dashboard|le\s+dashboard|la\s+dashboard|dashboard\s+en\s+entier|l[' ]ensemble\s+du\s+dashboard|de\s+la\s+page|du\s+site)\b/i.test(T);
    const isFollowUpBg = Memory && Memory.state && Memory.state.lastAction === 'dashboard_bg' &&
      /^(?:maintenant\s+)?(?:en\s+|est\s+)?(noir|blanc|sombre|gris|ardoise|bleu|rouge|vert|jaune|violet|orange|#[0-9a-f]{3,6})(?:\s+maintenant|\s+aussi)?$/i.test(T.trim());

    const mentionsVisuals = GLOBAL_SCOPE_RE.test(T) || /\b(visuels?|graphiques?)\b/.test(T);
    const isDashboardBg = isFollowUpBg || (isDashboardMention && !mentionsVisuals && (
      /(?:couleur|fond|arrie?re[- ]plan|background|colore|pein|teinte|#[0-9a-fA-F]{3,6}|rgba?)\b/i.test(T) ||
      /\b(?:en\s+)?(noir|blanc|sombre|gris|ardoise|bleu|rouge|vert|jaune|violet|orange|slate|dark)\b/i.test(T)
    ));

    if (isDashboardBg) {
      intent.action = 'dashboard_bg';
      const hexMatch = T.match(/#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b/);
      const rgbMatch = T.match(/rgba?\([^)]+\)/);
      if (hexMatch) {
        intent.dashboardBg = hexMatch[0];
      } else if (rgbMatch) {
        intent.dashboardBg = rgbMatch[0];
      } else {
        const matchEn = T.match(/(?:en\s+|de\s+couleur\s+|est\s+|:\s*)([a-z]+)\b/i);
        let colName = matchEn ? matchEn[1].toLowerCase() : null;
        if (!colName || (!COLORS[colName] && !/noir|blanc|sombre|gris|ardoise|slate|dark/.test(colName))) {
          const words = T.split(/\s+/);
          for (let i = words.length - 1; i >= 0; i--) {
            const w = words[i].toLowerCase();
            if (COLORS[w] || /noir|blanc|sombre|gris|ardoise|slate|dark/.test(w)) {
              colName = w;
              break;
            }
          }
        }
        if (colName) {
          if (/noir|sombre|dark/.test(colName)) intent.dashboardBg = '#0a0e17';
          else if (/gris|ardoise|slate/.test(colName)) intent.dashboardBg = '#111827';
          else if (/blanc/.test(colName)) intent.dashboardBg = '#f8fafc';
          else if (COLORS[colName]) intent.dashboardBg = COLORS[colName];
          else intent.dashboardBg = colName;
        } else {
          intent.dashboardBg = '#0a0e17';
        }
      }
      if (intent.format) {
        delete intent.format.barColor;
        delete intent.format.palette;
      }
      intent.confident = true;
      return intent;
    }

    // ── Filtre / Style global sur TOUS les visuels du dashboard ──
    const globalCue = /(bordure|border|ombre|shadow|halo|neon|flou|blur|arrondi|radius|couleur|colore|theme|palette|fond|arrie?re[- ]plan|background|etiquette|label|legende|filtr|seulement|uniquement|\bgarde\b|(?:efface|retire|supprime|reinitialise|annule)\s+(?:les?\s+)?filtres?|\breset\b|\ben\s+(?:rouge|bleu|vert|jaune|orange|violet|rose|cyan|gris|noir|blanc)\b|#[0-9a-f]{3,6}|\btop\s*\d+)/;
    const isGlobalFilter = (GLOBAL_SCOPE_RE.test(T) || /(?:efface|retire|supprime|reinitialise|annule|reset)\s+(?:les?\s+|tous\s+les\s+)?filtres?/.test(T) ||
      /(?:filtrer?|afficher|garder)\s+(?:toute?\s+)?(?:le\s+|la\s+)?(?:dashboard|tableau de bord)/.test(T)) && globalCue.test(T);
    if (isGlobalFilter) {
      intent.action = 'global_filter';
      intent.globalStyle = intent.format || {};
      if (/(?:efface|retire|supprime|reinitialise|annule|reset)\s+(?:les?\s+)?filtres?/.test(T)) intent.clearFilter = true;
      else if (/(filtr|seulement|uniquement|\bgarde\b)/.test(T)) intent.globalDataFilter = true; // résolu dans execute()
      intent.confident = true;
      return intent;
    }

    const undoCue = /^(annule|defais|undo|reviens en arriere|retire le dernier)/.test(T.trim()) || /(annule (?:le )?(?:dernier|ce) (?:visuel|graphique)|annule ca)/.test(T);
    const deleteCue = /(supprim|efface|enleve|retire (?:ce|le|la|cet)|delete|remove)/.test(T) && !/(top|limite|legende|etiquette|label|ombre|flou|filtre|couleur)/.test(T);
    const listCue = /(quels? (?:sont )?(?:les )?(?:kpi|indicateurs?|mesures?)|liste (?:des |les )?(?:kpi|indicateurs)|kpi disponibles?)/.test(T);
    const explainCue = /(explique|pourquoi|c est quoi (?:ce|cet)|comment (?:tu as|as tu|est[- ]ce) (?:calcule|fait|calcul)|montre (?:moi )?(?:le )?(?:dax|sql)|\bdax\b|\bsql\b|que (?:montre|represente))/.test(T) && !intent.groups.length;
    const showCue = /(affiche|montre|voir|fais voir|ou est|focus|zoom)\s+(?:moi\s+)?(?:le\s+|ce\s+)?(?:visuel|graphique|chart|dashboard|tableau de bord)\b/.test(T) && !/(cree|ajouter|nouveau|nouvelle|autre|pie|bar|donut|line)/.test(T);
    const hasExplicitNew = /(autre|nouveau|nouvelle|un autre|une autre)\b/.test(T);
    const hasExplicitModify = /(modifie|modifier|change|remplace|corrige|rectifie|sur le meme|ce visuel|le precedent)/.test(T);
    const isNewVisual = hasExplicitNew || (!hasExplicitModify && (/(^|\s)(?:un|une)\s+(?:autre\s+)?(?:visuel|graphique|chart|carte|pie|bar|donut|courbe)\b/.test(T) || /(dans\s+un\s+(?:visuel|graphique|chart))/.test(T)));
    const createVerb = isNewVisual || (!hasExplicitModify && /(\bcree\b|creer|genere|generer|ajoute|ajouter|nouveau|nouvelle|construis|\bfais\b|fait moi|donne moi|je veux\s+(?:un|une|des)|je voudrais|build|create|add|visualise|trace|dessine)/.test(T));
    const updateCue = /(change|modifie|modifier|passe|transforme|convertis|\bmets?\b|rends|ajuste|colore|masque|cache|applique|remplace|update|\bset\b|corrige|rectifie|\bfixe\b|limite|restreins|filtre|reduis|adapte|\bjuste\b|seulement|uniquement|garde|pas tout|au lieu|a la place|plutot|\bmonte\b|descends|augmente)/.test(T);
    const refExisting = /(ce\s+(?:visuel|graphique|chart)|le\s+(?:meme|dernier|precedent|actuel)\s+(?:visuel|graphique|chart)?|sur\s+le\s+meme|sur\s+ce\s+visuel|visuel\s+(?:actuel|precedent|existant)|l'actuel|le\s+precedent|le\s+dernier|\bexistant\b)/.test(T);
    const isRestrictive = !isNewVisual && !createVerb && updateCue && (intent.topN !== null || intent.clearTop);
    const isModifyRef = (hasExplicitModify || refExisting) && !hasExplicitNew;
    intent._flags = { hasFormat, explicitNew: hasExplicitNew || /(ajoute|en plus|aussi un)/.test(T), updateCue, createVerb };

    const confirmCue = /^(oui|ok|exact|parfait|bien|super|cool|bravo|c est ca|c est bien|tres bien|d accord|voila|ya|yep|yes|nickel|impeccable|correct|c est correct|bonne reponse|tu as bien|tu as raison|effectivement|en effet|tu reprend|vous reprenez)\b/.test(T.trim())
      && T.trim().split(/\s+/).length <= 12
      && !intent.groups.length && !hasFormat && !intent.chartExplicit && intent.topN === null && !intent.sort && !intent.clearTop;

    if (confirmCue) {
      intent.action = 'chat';
      intent.chatReply = Memory.hasContext()
        ? "Parfait ! 😊 Le visuel est à jour. Tu veux ajuster autre chose (couleur, top N, type de graphique) ou en créer un nouveau ?"
        : "Compris ! 😊 Dis-moi ce que tu veux afficher — KPI, dimension, type de graphique — et je m'en occupe.";
    } else if (undoCue) intent.action = 'undo';
    else if (explainCue) intent.action = 'explain';
    else if (showCue) intent.action = 'show';
    else if (deleteCue) intent.action = 'delete';
    else if (listCue) intent.action = 'list';
    else if (isModifyRef || isRestrictive) intent.action = 'update';
    else if (isNewVisual) intent.action = 'create';
    else if (updateCue && !createVerb) intent.action = 'update';
    else if (intent.groups.length) intent.action = 'create';
    else if (hasFormat || intent.chartExplicit || intent.title) intent.action = 'update';

    if (intent.action === 'unknown' && !intent.groups.length) {
      const st = smallTalk(T.trim());
      if (st) { intent.action = 'chat'; intent.chatReply = st; }
    }
    intent.confident = ['delete', 'list', 'show', 'chat', 'undo', 'explain'].includes(intent.action) ||
      (intent.action === 'update' && (hasFormat || intent.chartExplicit || isModifyRef || isRestrictive)) ||
      (intent.action === 'create' && (match.bestScore >= 3 || isNewVisual));
    return intent;
  }

  /* ═══════════════════════ RECHERCHE DE VISUEL PAR TITRE ═══════════════════════ */
  function findVisualByTitleOrPrompt(text) {
    const D = root.Dashboard;
    const reg = D && D.getRegistry ? D.getRegistry() : {};
    const items = [...Visuals.items];
    Object.keys(reg).forEach(k => {
      const existing = items.find(v => v.id === k);
      if (!existing) {
        items.push({
          id: k,
          sid: (reg[k].config && reg[k].config._agentSid) || k,
          cfg: reg[k].config || {},
          style: reg[k].containerStyle || {},
          legacy: true
        });
      } else if (reg[k].config) {
        existing.cfg = Object.assign({}, reg[k].config, existing.cfg || {});
      }
    });
    if (!items.length) return null;

    const textRaw = normalizeTypos(String(text || ''));
    const textA = ascii(textRaw).replace(/[-–—_:;,.]+/g, ' ');
    const textTokens = textA.split(/\s+/).filter(w => w.length >= 2);
    const textAlpha = ascii(textRaw).replace(/[^a-z0-9]+/g, ' ').trim();

    // 0. Ordinal / index match : "visuel 1", "visuel #2", "premier visuel", "dernier visuel", "visuel-card-1"
    if (/premier\s+(?:visuel|graphique|chart)/i.test(textA) && items.length) return items[0];
    if (/dernier\s+(?:visuel|graphique|chart)/i.test(textA) && items.length) return items[items.length - 1];
    const numMatch = textA.match(/(?:visuel|carte|graphique|chart)\s*(?:numero|no|#)?\s*(\d+)\b/i);
    if (numMatch) {
      const idx = parseInt(numMatch[1], 10);
      if (idx >= 1 && idx <= items.length) return items[idx - 1];
      const byCardId = items.find(v => v.id === `visual-card-${idx}` || (v.sid && v.sid.includes(String(idx))));
      if (byCardId) return byCardId;
    }

    // 1. Quoted title match: "...", «...», '...'
    const quoted = textRaw.match(/["«'“](.+?)["»'”]/);
    if (quoted) {
      const qA = ascii(quoted[1]).replace(/[^a-z0-9]+/g, ' ').trim();
      if (qA.length >= 3) {
        for (let i = items.length - 1; i >= 0; i--) {
          const v = items[i];
          const t = ascii((v.cfg && v.cfg.title) || '').replace(/[^a-z0-9]+/g, ' ').trim();
          if (t.includes(qA) || qA.includes(t)) return v;
        }
      }
    }

    // 2. Extracted title cue match: "pour le visuel <TITRE> [je veux... / change...]"
    const cueMatch = textA.match(/(?:pour|sur|dans|le|du|au|concernant|modifie|change)?\s*(?:le\s+|ce\s+|la\s+)?(?:visuel|graphique|chart|carte|diagramme)\s+(?:intitule|titre|nomme|appele|de)?\s*[:«"']?\s*(.+?)(?=\s+(?:je\s+veux|mets|change|passe|avec|au\s+lieu|couleur|bordure|filtre|supprime|en\s+|vers\s+)|$|[?.,!])/i);
    if (cueMatch && cueMatch[1]) {
      const cueTarget = ascii(cueMatch[1]).replace(/[^a-z0-9]+/g, ' ').trim();
      if (cueTarget.length >= 3) {
        for (let i = items.length - 1; i >= 0; i--) {
          const v = items[i];
          const t = ascii((v.cfg && v.cfg.title) || '').replace(/[^a-z0-9]+/g, ' ').trim();
          if (t.length >= 3 && (t.includes(cueTarget) || cueTarget.includes(t))) return v;
        }
        const cueWords = cueTarget.split(/\s+/).filter(w => w.length >= 2 && !STOP.has(w));
        if (cueWords.length >= 2) {
          let bestC = null, bestCount = 0;
          for (let i = items.length - 1; i >= 0; i--) {
            const v = items[i];
            const t = ascii((v.cfg && v.cfg.title) || '').replace(/[^a-z0-9]+/g, ' ').trim();
            const tWords = t.split(/\s+/).filter(w => w.length >= 2 && !STOP.has(w));
            const matchedCount = cueWords.filter(w => tWords.includes(w)).length;
            if (matchedCount >= 2 && matchedCount > bestCount) {
              bestCount = matchedCount;
              bestC = v;
            }
          }
          if (bestC) return bestC;
        }
      }
    }

    // 3. Exact or normalized alphanumeric substring match against the whole prompt
    for (let i = items.length - 1; i >= 0; i--) {
      const v = items[i];
      const t = ascii((v.cfg && v.cfg.title) || '').replace(/[^a-z0-9]+/g, ' ').trim();
      if (t.length >= 4 && textAlpha.includes(t)) return v;
    }

    // 4. Substring without "Top X" prefix
    for (let i = items.length - 1; i >= 0; i--) {
      const v = items[i];
      const rawTitle = (v.cfg && v.cfg.title) || '';
      const t = ascii(rawTitle).replace(/[^a-z0-9]+/g, ' ').replace(/\btop\s*\d+\b/g, '').trim();
      if (t.length >= 4 && textAlpha.includes(t)) return v;
    }

    // 5. [CORRECTIF 6] Token overlap match (ratio >= 60 % des mots significatifs du titre)
    const stopW = new Set(['le', 'la', 'les', 'un', 'une', 'des', 'du', 'de', 'sur', 'dans', 'pour', 'ce', 'cet', 'cette', 'visuel', 'graphique', 'chart', 'en', 'par', 'et', 'au', 'aux', 'top']);
    const tokSet = new Set(textTokens.map(stem));
    let bestV = null, bestRatio = 0, bestHit = 0;
    for (let i = items.length - 1; i >= 0; i--) {
      const v = items[i];
      const t = ascii((v.cfg && v.cfg.title) || '').replace(/[^a-z0-9]+/g, ' ').trim();
      const tt = t.split(/\s+/).filter(w => w.length >= 2 && !stopW.has(w) && !/^\d+$/.test(w)).map(stem);
      if (!tt.length) continue;
      const hit = tt.filter(w => tokSet.has(w)).length, ratio = hit / tt.length;
      if (hit >= 2 && ratio >= 0.6 && (ratio > bestRatio || (ratio === bestRatio && hit > bestHit))) { bestRatio = ratio; bestHit = hit; bestV = v; }
    }
    return bestV;
  }

  /* ═══════════════════════ RÉSOLUTION CONTEXTUELLE ═══════════════════════ */
  function stripVisualRef(text, v) {
    const raw = String(text);
    const q = raw.match(/["«“](.+?)["»”]/);
    if (q) return raw.replace(q[0], ' ').replace(/\b(?:le|ce)\s+(?:visuel|graphique|chart)\s*(?:intitul[eé]|nomm[eé]|appel[eé])?/gi, ' ').replace(/\s+/g, ' ').trim();
    const A = ascii(raw), title = (v.cfg && v.cfg.title) || '';
    const toks = ascii(title).replace(/[^a-z0-9]+/g, ' ').trim().split(' ').filter(Boolean);
    if (toks.length) {
      const m = A.match(new RegExp(toks.map(escRe).join('[^a-z0-9]+'), 'i'));
      if (m) return (raw.slice(0, m.index) + ' ' + raw.slice(m.index + m[0].length))
        .replace(/\b(?:pour|sur|dans)?\s*(?:le|ce)\s+(?:visuel|graphique|chart)\b/gi, ' ').replace(/\s+/g, ' ').trim();
    }
    const cue = A.match(/(?:le|ce|la)?\s*(?:visuel|graphique|chart)\s+(.+?)(?=\s+(?:je veux|mets?|change[rz]?|modifie[rz]?|passe|remplace|applique|ajoute|avec|au lieu|couleur|bordure|ombre|fond|arriere|filtre|filtrer|supprime|efface|affiche|etiquettes?|legende|flou|arrondi|top\s+\d+|en\s+(?:rouge|bleu|vert|jaune|violet|orange|rose|cyan|gris|noir|blanc|barres?|camembert|pie|donut|ligne|courbe|card))|$)/);
    if (cue) return (raw.slice(0, cue.index) + ' ' + raw.slice(cue.index + cue[0].length)).replace(/\s+/g, ' ').trim();
    return raw;
  }

  function resolveWithContext(text, intent, forcedTarget) {
    // ── Résolution par titre : "sur le visuel X change..." / "supprime visuel X" ──
    const matchedV = forcedTarget || findVisualByTitleOrPrompt(text);
    if (matchedV) {
      Memory.state.activeSid = matchedV.sid;
      intent.targetVisualId = matchedV.id;
      intent.targetSid = matchedV.sid;
      intent.targetVisual = matchedV;
      const D = root.Dashboard;
      if (D && D.setActiveCardId) {
        try { D.setActiveCardId(matchedV.id); } catch (e) { }
      }
    }
    const spec = activeSpec(intent);
    const T = ascii(normalizeTypos(text)), P = normWords(expandAbbreviations(normalizeTypos(text)));
    const out = Object.assign({}, intent, { notes: intent.notes.slice(), format: Object.assign({}, intent.format) });
    if (['chat', 'list', 'delete', 'show', 'undo', 'explain', 'dashboard_bg', 'global_filter'].includes(out.action)) return out;

    // ── [CORRECTIF 5] Visuel nommé mais introuvable → on ne modifie pas un autre visuel en silence ──
    if (!matchedV && out.action !== 'create') {
      const nm = T.match(/\b(?:pour|sur|dans|concernant)\s+(?:le|ce)\s+(?:visuel|graphique|chart)\s+(.{4,}?)\s+(?:je veux|mets|met|change|passe|avec|au lieu|couleur|bordure|filtre|supprime|en )/);
      if (nm && !/^(actuel|precedent|dernier|meme|existant)/.test(nm[1])) {
        const Dd = root.Dashboard, titles = (Dd && Dd.list ? Dd.list() : []).map(v => '• « ' + v.title + ' »');
        out.action = 'chat'; out.confident = true;
        out.chatReply = `Je ne retrouve pas le visuel « ${nm[1]} ». Visuels disponibles :\n` + (titles.join('\n') || '(aucun)') + '\n\nRecopie le titre exact et je le modifie.';
        return out;
      }
    }

    if (matchedV) {
      out.targetVisualId = matchedV.id;
      out.targetSid = matchedV.sid;
      out.targetVisual = matchedV;
      out.action = 'update';
      out.confident = true;
      out.notes.push(`Cible identifiée par titre : « ${(matchedV.cfg && matchedV.cfg.title) || matchedV.id} ».`);
      // Si le visuel ciblé est legacy (aucun spec), on retourne directement out pour execution via legacyUpdate
      if (!spec) return out;
    } else if (!spec) {
      return intent;
    }

    // ── [CORRECTIF 5] Comparaison existante : changement de pays de référence / fusion des couleurs ──
    if (spec && spec.comparison) {
      const base = spec.comparison, oldA = ascii(base.baseline).trim();
      const swapCue = /(au lieu de|a la place de|plutot que|remplace|change[rz]?\s+(?:moi\s+)?(?:le\s+)?(?:pays|baseline|reference)|par rapport a|reference|baseline)/.test(T);
      let newBL = null;
      if (swapCue) {
        const stripped = T.replace(new RegExp(escRe(oldA), 'g'), ' ');
        const cand = extractBaseline(stripped);
        if (cand && ascii(cand.countryLabel).trim() !== oldA) newBL = cand;
      }
      if (newBL) {
        out.comparison = Object.assign({}, base, {
          baseline: newBL.countryLabel, baselineRate: newBL.rate, threshold: newBL.rate,
          rateField: newBL.rateField || base.rateField,
          betterLabel: 'Meilleur que ' + newBL.countryLabel, worseLabel: 'Pire que ' + newBL.countryLabel,
          fallback: newBL.fallback || null, partialCue: false
        });
        out.groups = []; out.action = 'update'; out.chartType = spec.chartType; out.chartExplicit = false; out.confident = true;
        out.notes.push(`Contexte : pays de référence → « ${newBL.countryLabel} » (taux ${newBL.rate}).`);
      } else if (out.comparison && out.comparison.partialCue) {
        const c = out.comparison;
        out.comparison = Object.assign({}, base, {
          colorBetter: c.explicitBetter ? c.colorBetter : base.colorBetter,
          colorWorse: c.explicitWorse ? c.colorWorse : base.colorWorse,
          partialCue: false
        });
        out.action = 'update'; out.chartExplicit = false; out.chartType = spec.chartType;
        out.notes.push('Contexte : couleurs de la comparaison mises à jour.');
      }
    }

    const lastGroups = groupsFromIds(spec.measureIds);
    if (out.groups.length && out.groups.every(g => g.dimOnly) && !(intent._flags && intent._flags.createVerb)) {
      out.groups = []; out.notes.push('Contexte : aucune nouvelle mesure citée, je garde celle du visuel courant.');
    }
    const hasMod = out.chartExplicit || out.topN !== null || out.clearTop || !!out.sort || !!out.title || Object.keys(out.format).length > 0 || !!out.legendFragment || !!out.comparison;
    const shortMsg = T.trim().split(/\s+/).length <= 9;
    const anaphora = /(\bet\b|aussi|pareil|meme chose|plutot|a la place|maintenant|ensuite|finalement|celui|celle|\bca\b|le meme|la meme|au lieu)/.test(T);

    if (!out.groups.length && lastGroups.length && lastGroups[0].kind === 'dataset') {
      const fam = lastGroups[0].measures[0].family;
      let sw = null;
      ensureCatalog().datasets.forEach(d => {
        if (sw || d.key === lastGroups[0].ds.key) return;
        if (!d.dimTerms.some(t => has(P, t))) return;
        const mm = d.measures.find(x => x.family === fam);
        if (mm) sw = { kind: 'dataset', ds: d, measures: [mm], score: 5 };
      });
      if (sw) {
        out.groups = [sw]; out.inherited = 'dimension';
        out.notes.push(`Contexte : même mesure « ${sw.measures[0].label} », nouvelle dimension « ${sw.ds.dimLabel} ».`);
        if (!out.chartType && spec.chartType) out.chartType = spec.chartType;
        if (out.action === 'unknown' || out.action === 'update' && !intent._flags.updateCue) out.action = 'create';
      }
    }
    const needsData = out.chartExplicit || out.topN !== null || out.clearTop || !!out.sort || !!out.legendFragment || (out.filterCue && !out.groups.length) || !!out.comparison;
    // On n'hérite pas des données du visuel précédent si un visuel précis a été ciblé par titre
    if (!matchedV && !out.groups.length && lastGroups.length && needsData && (shortMsg || anaphora || out.action === 'update' || out.action === 'unknown')) {
      out.groups = lastGroups; out.inherited = 'groups';
      out.notes.push('Contexte : je modifie le visuel précédent (mêmes données).');
      if (out.action === 'unknown' || out.action === 'create' && !intent._flags.createVerb) out.action = 'update';
    }
    if (out.action === 'unknown' && hasMod) out.action = 'update';
    if (out.groups.length && !out.inherited && !out.chartType && spec.chartType && out.action === 'create' && shortMsg && anaphora) {
      out.chartType = spec.chartType; out.notes.push(`Contexte : même type de graphique (${spec.chartType}).`);
    }
    if (out.inherited || out.action === 'update') out.confident = true;
    return out;
  }

  /* ═══════════════════════ CLARIFICATION ═══════════════════════ */
  function slimIntent(i) {
    return { text: i.text, textAscii: i.textAscii, action: i.action, chartType: i.chartType, chartExplicit: i.chartExplicit, topN: i.topN, clearTop: i.clearTop, sort: i.sort, title: i.title, format: i.format, colorMentions: i.colorMentions, legendFragment: i.legendFragment, filterCue: i.filterCue, comparison: i.comparison, notes: [], groups: [], _flags: i._flags };
  }
  function buildKpiOptions(prompt, pre) {
    const opts = [], seen = new Set();
    const push = (id, label) => { if (id && !seen.has(id) && opts.length < CFG.clarifyOptions) { seen.add(id); opts.push({ id, label }); } };
    (pre || []).forEach(c => { const f = findById(c.id); if (f) push(c.id, f.kind === 'summary' ? `${f.item.label} (indicateur global)` : measureLabel(f.measure, f.ds)); });
    const ctx = Memory.lastUserText();
    RAGStore.search(prompt + ' ' + ctx, 12).forEach(c => {
      if (c.source === 'measure_meta') push(c.meta.measureId, `${c.meta.label} par ${c.meta.dimLabel}`);
      else if (c.source === 'summary_kpi') push(c.meta.summaryId, `${c.meta.label} (indicateur global)`);
    });
    const cat = ensureCatalog();
    cat.datasets.forEach(d => push(d.measures[0].id, measureLabel(d.measures[0], d)));
    cat.summary.slice(0, 2).forEach(s => push(s.id, `${s.label} (indicateur global)`));
    return opts;
  }
  function askWhichKpi(intent, pre) {
    const options = buildKpiOptions(intent.text, pre);
    if (!options.length) return { reply: "Aucun KPI n'est disponible : les données (BI_DATA_STORE) semblent vides.", created: [] };
    Memory.setPending({ type: 'choose_kpi', options, intent: slimIntent(intent) });
    return {
      reply: "Je n'ai pas identifié l'indicateur avec certitude. Tu veux dire :\n" + options.map((o, i) => `${i + 1}. ${o.label}`).join('\n') + "\n\nRéponds par un numéro (ou le nom).",
      created: [], needsInput: true, suggestions: options.map((o, i) => String(i + 1) + ' — ' + o.label.slice(0, 28))
    };
  }
  function resolvePending(text) {
    const p = Memory.state.pending; if (!p) return null;
    const T = ascii(text).trim();
    // Strict cancel ONLY: "annule", "stop", "annuler", "non merci", or "non" alone
    if (/^(annule|laisse tomber|stop|oublie|non merci|annuler)\s*$/i.test(T) || /^non\s*$/i.test(T)) {
      return { p, cancel: true };
    }
    // Si l'utilisateur commence par "non", le retirer pour analyser le reste ("non brand par region" -> "brand par region")
    const cleanText = text.replace(/^non[\s,;:.-]+/i, '').trim();
    const cleanT = ascii(cleanText).trim();
    const cleanP = normWords(cleanText);

    if (p.type === 'choose_kpi') {
      let idx = -1;
      const num = cleanT.match(/^(?:le\s+|la\s+|n\s*|option\s*|choix\s*)?(\d+)\b/);
      if (num) idx = parseInt(num[1], 10) - 1;
      else {
        const words = cleanText.split(/[\s,;:.-]+/).filter(w => w.length >= 3);
        idx = p.options.findIndex(o => {
          const oNorm = normWords(o.label);
          return words.some(w => has(oNorm, w)) || has(cleanP, o.label.replace(/\(.*?\)/g, ''));
        });
      }
      if (idx >= 0 && p.options[idx]) return { p, choice: p.options[idx] };
      Memory.clearPending();
      return null;
    }
    if (p.type === 'confirm' && /^(oui|ok|d accord|vas y|go|yes|bien sur|exact|c est ca)\b/.test(T)) return { p, yes: true };
    return null;
  }

  /* ═══════════════════════ LLM ═══════════════════════ */
  function catalogLines(P) {
    const cat = ensureCatalog(), entries = [];
    cat.summary.forEach(s => entries.push({ id: s.id, label: s.label, type: 'indicateur', syn: s.terms, score: s.terms.filter(t => has(P, t)).length }));
    cat.datasets.forEach(d => d.measures.forEach(me => entries.push({ id: me.id, label: me.label + ' par ' + d.dimLabel, type: d.dimIsTime ? 'série temporelle' : 'répartition', syn: me.terms.concat(d.dimTerms), score: me.terms.filter(t => has(P, t)).length + d.dimTerms.filter(t => has(P, t)).length })));
    entries.sort((a, b) => b.score - a.score);
    return entries.slice(0, CFG.maxLLMEntries).map(e => `${e.id} | ${e.label} | ${e.type} | ${e.syn.slice(0, 4).join(', ')}`).join('\n');
  }
  function stateSummary() {
    const s = activeSpec();
    if (!s) return 'Aucun visuel actif';
    return `Dernière mesure: ${s.measureIds.join(', ')} | type: ${s.chartType || 'auto'} | top N: ${s.topN || 'tous'} | filtre: ${(s.filterValues || []).join(', ') || 'aucun'} | comparaison: ${s.comparison ? s.comparison.betterLabel + '/' + s.comparison.worseLabel : 'non'} | visuels: ${Visuals.count()}`;
  }
  async function llmFetch(messages, json) {
    const ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    const timer = ctrl ? setTimeout(() => ctrl.abort(), CFG.timeoutMs) : null;
    try {
      const body = { model: CFG.model, stream: false, options: { temperature: json ? 0 : 0.4, num_ctx: 4096 }, messages };
      if (json) body.format = 'json';
      let r;
      const primaryUrl = (CFG.ollamaProxyUrl || CFG.ollamaUrl).replace(/\/$/, '');
      try {
        r = await fetch(primaryUrl + '/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: ctrl ? ctrl.signal : undefined, body: JSON.stringify(body) });
        if (!r.ok && primaryUrl !== CFG.ollamaUrl.replace(/\/$/, '')) throw new Error('Proxy status ' + r.status);
      } catch (errProxy) {
        // Repli direct sur l'URL native d'Ollama
        r = await fetch(CFG.ollamaUrl.replace(/\/$/, '') + '/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: ctrl ? ctrl.signal : undefined, body: JSON.stringify(body) });
      }
      if (!r || !r.ok) throw new Error('HTTP ' + (r ? r.status : 'offline'));
      const data = await r.json();
      return (data.message && data.message.content) ? data.message.content : (data.response || '');
    } finally { if (timer) clearTimeout(timer); }
  }
  async function callLLMWithRAG(text, ragContext) {
    const system = "Tu analyses la demande d'un utilisateur pour un tableau de bord BI, EN TENANT COMPTE DE LA CONVERSATION. " +
      "Si la demande est elliptique, réutilise la mesure de l'état courant. Réponds UNIQUEMENT par un JSON valide.\n" +
      "Catalogue des KPI :\n" + catalogLines(normWords(text)) + (ragContext ? '\n\n' + ragContext + '\n' : '') +
      '\nÉtat courant : ' + stateSummary() +
      '\n{"action":"create|update|delete|list|chat|explain|undo|unknown","chart_type":"bar|pie|donut|line|scatter|treemap|card|null","kpi_ids":[],"top_n":null,"sort":"desc|asc|null","title":null,"uses_previous_context":false}' +
      "\nRègles : n'invente jamais d'id.";
    const raw = await llmFetch([{ role: 'system', content: system }].concat(Memory.history(CFG.llmHistoryTurns), [{ role: 'user', content: text }]), true);
    const jsonMatch = raw.match(/\{[\s\S]*\}/);
    if (!jsonMatch) throw new Error('Réponse LLM non-JSON');
    return JSON.parse(jsonMatch[0]);
  }
  async function callLLMChat(text) {
    const system = "Tu es un assistant BI francophone, chaleureux et concis (3 phrases max). KPI disponibles :\n" + catalogLines(normWords(text)).split('\n').slice(0, 15).join('\n') + "\nÉtat : " + stateSummary() + "\nSi la demande est floue, pose UNE question de clarification.";
    return (await llmFetch([{ role: 'system', content: system }].concat(Memory.history(CFG.llmHistoryTurns), [{ role: 'user', content: text }]), false)).trim();
  }
  function mergeLLM(rule, llm) {
    if (PROTECTED_ACTIONS.includes(rule.action)) return rule;
    const out = Object.assign({}, rule, { notes: rule.notes.slice(), format: Object.assign({}, rule.format) });
    if (!llm || typeof llm !== 'object') return out;
    const validAction = ACTIONS.includes(llm.action) && llm.action !== 'unknown';
    const llmGroups = groupsFromIds(Array.isArray(llm.kpi_ids) ? llm.kpi_ids : []);
    if (llmGroups.length && (rule.bestScore < 5 || !out.groups.length)) {
      out.groups = llmGroups; out.notes.push(`KPI via LLM (${CFG.model}).`);
      if (out.action === 'unknown') out.action = (llm.action === 'update' && activeVisualId()) ? 'update' : 'create';
    }
    if (out.action === 'unknown' && validAction) out.action = llm.action;
    if (!out.chartExplicit && CHART_TYPES.includes(llm.chart_type)) out.chartType = llm.chart_type;
    if (out.topN == null && Number.isInteger(llm.top_n) && llm.top_n > 0) out.topN = llm.top_n;
    if (!out.sort && (llm.sort === 'asc' || llm.sort === 'desc')) out.sort = llm.sort;
    if (!out.title && typeof llm.title === 'string' && llm.title.trim()) out.title = llm.title.trim().slice(0, 120);
    if (llm.uses_previous_context && !out.groups.length && activeMeasureIds().length) { out.groups = groupsFromIds(activeMeasureIds()); out.inherited = 'llm'; }
    return out;
  }

  /* ═══════════════════════ GEMINI FALLBACK ═══════════════════════ */
  function computeIntentConfidence(i) {
    if (!i) return 0;
    if (PROTECTED_ACTIONS.includes(i.action)) return 0.95;
    let s = 0;
    if (i.groups && i.groups.length) s += 0.35;
    if (i.inherited) s += 0.25;
    if (i.chartExplicit) s += 0.15;
    if (i.topN !== null) s += 0.1;
    if (i.comparison) s += 0.25;
    if (i.confident) s += 0.2;
    if (i.ambiguous) s -= 0.3;
    if (i.bestScore < 3) s -= 0.2;
    return Math.max(0, Math.min(1, s));
  }

  async function callGeminiFallback(text, ragContext) {
    if (!CFG.geminiEnabled || !CFG.geminiApiKey) return null;

    const systemPrompt = [
      "Tu es un analyste BI. Traduis la demande utilisateur en une intention structurée pour construire un visuel Apache Superset.",
      "",
      "Catalogue des KPI disponibles (id | label | dimension | type) :",
      catalogLines(normWords(text)),
      "",
      "Contexte conversationnel :",
      stateSummary(),
      "",
      "Retourne UNIQUEMENT un JSON valide, sans markdown :",
      `{
  "action": "create" | "update" | "delete" | "list" | "chat" | "explain" | "undo",
  "chart_type": "bar" | "pie" | "donut" | "line" | "scatter" | "treemap" | "card" | null,
  "kpi_ids": ["id_du_catalogue", ...],
  "top_n": number | null,
  "sort": "desc" | "asc" | null,
  "title": string | null,
  "comparison": {
    "type": "rate_vs_baseline",
    "baseline": "France",
    "betterLabel": "Meilleur que France",
    "worseLabel": "Pire que France",
    "colorBetter": "#ef4444",
    "colorWorse": "#eab308",
    "threshold": 1.0872
  } | null,
  "filter_values": ["France", "Tunisie"] | [],
  "colors": ["#ef4444", "#eab308"] | [],
  "notes": string
}`,
      "",
      "Règles CRUCIALES :",
      "1. N'invente JAMAIS d'id : pioche UNIQUEMENT dans le catalogue.",
      "2. Si l'utilisateur compare deux groupes ('meilleur/pire que X', 'plus fort/faible que Y'), remplis `comparison`.",
      "3. Utilise le KPI `macro_countries.rate_usd` pour toute comparaison par devise.",
      "4. Si l'utilisateur cite des couleurs pour des catégories, remplis `colors` dans l'ordre.",
      "5. Pour un camembert > 8 catégories, mets `top_n = 8` SAUF si `comparison` est défini.",
      "6. Si ambigu, mets action='chat' et explique en une phrase."
    ].join('\n');

    const url = `${CFG.geminiEndpoint}/${CFG.geminiModel}:generateContent`;
    const ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    const timer = ctrl ? setTimeout(() => ctrl.abort(), CFG.geminiTimeoutMs) : null;

    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-goog-api-key': CFG.geminiApiKey },
        signal: ctrl ? ctrl.signal : undefined,
        body: JSON.stringify({
          contents: [{ role: 'user', parts: [{ text: systemPrompt + '\n\nDemande utilisateur :\n' + text }] }],
          generationConfig: { temperature: 0.1, responseMimeType: 'application/json' }
        })
      });
      if (!res.ok) { const errBody = await res.text(); throw new Error(`Gemini HTTP ${res.status} : ${errBody.slice(0, 200)}`); }
      const data = await res.json();
      const raw = data && data.candidates && data.candidates[0] && data.candidates[0].content && data.candidates[0].content.parts && data.candidates[0].content.parts[0] && data.candidates[0].content.parts[0].text;
      if (!raw) throw new Error('Réponse Gemini vide');
      const jsonMatch = raw.match(/\{[\s\S]*\}/);
      if (!jsonMatch) throw new Error('Gemini : réponse non-JSON');
      return JSON.parse(jsonMatch[0]);
    } catch (e) {
      console.warn('[BIAgent.Gemini] échec fallback :', e.message);
      return null;
    } finally { if (timer) clearTimeout(timer); }
  }

  function mergeGemini(rule, g) {
    if (!g || typeof g !== 'object') return rule;
    if (PROTECTED_ACTIONS.includes(rule.action)) return rule;
    const out = Object.assign({}, rule, { notes: rule.notes.slice(), format: Object.assign({}, rule.format) });
    if (ACTIONS.includes(g.action) && (rule.action === 'unknown' || (rule.action === 'create' && !rule.groups.length))) out.action = g.action;
    const ids = Array.isArray(g.kpi_ids) ? g.kpi_ids.filter(id => findById(id)) : [];
    if (ids.length) {
      const gs = groupsFromIds(ids);
      if (gs.length) { out.groups = gs; out.notes.push('KPI via Gemini (fallback sémantique).'); }
    }
    if (CHART_TYPES.includes(g.chart_type) && !out.chartExplicit && out.action === 'create') { out.chartType = g.chart_type; out.chartExplicit = true; }
    if (Number.isInteger(g.top_n) && g.top_n > 0) out.topN = g.top_n;
    if (g.sort === 'asc' || g.sort === 'desc') out.sort = g.sort;
    if (typeof g.title === 'string' && g.title.trim()) out.title = g.title.trim().slice(0, 120);
    if (g.comparison && typeof g.comparison === 'object') {
      const baseline = g.comparison.baseline || 'USA';
      const threshold = Number(g.comparison.threshold) || (baseline.toUpperCase() === 'USD' || baseline.toUpperCase() === 'USA' ? 1 : 1);
      out.comparison = {
        type: g.comparison.type || 'rate_vs_baseline',
        baseline,
        baselineRate: threshold,
        rateField: 'rate_usd',
        betterLabel: g.comparison.betterLabel || ('Meilleur que ' + baseline),
        worseLabel: g.comparison.worseLabel || ('Pire que ' + baseline),
        colorBetter: g.comparison.colorBetter || '#ef4444',
        colorWorse: g.comparison.colorWorse || '#eab308',
        threshold
      };
      out.notes.push('Comparaison binaire détectée par Gemini.');
    }
    if (Array.isArray(g.filter_values) && g.filter_values.length) {
      out.filterValues = g.filter_values;
      out.notes.push(`Légende/filtre : ${g.filter_values.join(', ')}`);
    }
    if (Array.isArray(g.colors) && g.colors.length >= 2 && out.comparison) {
      out.comparison.colorBetter = g.colors[0];
      out.comparison.colorWorse = g.colors[1];
    }
    if (g.action === 'chat' && g.notes) out.chatReply = g.notes;
    out.confident = true;
    return out;
  }

  /* ═══════════════════════ CORRECTIVE RAG ═══════════════════════ */
  const contentTokensRaw = text => ascii(text).replace(/[^a-z0-9]+/g, ' ').split(' ').filter(w => w.length >= 2 && !STOP.has(w) && !/^\d+$/.test(w));
  function tokenGroups(rawTokens) {
    return rawTokens.map(raw => {
      const set = new Set([stem(raw)]);
      synFor(raw).forEach(p => normWords(p).trim().split(' ').forEach(w => { if (w.length >= 3) set.add(w); }));
      return set;
    });
  }
  function gradeChunks(groups, chunks) {
    if (!groups.length) return { verdict: 'incorrect', kept: [], coverage: 0, best: 0 };
    const sat = (ct, gp) => { for (const w of gp) if (ct.has(w)) return true; return false; };
    const graded = chunks.map(c => {
      const ct = new Set(c.tokens.map(stem)); let hit = 0;
      groups.forEach(gp => { if (sat(ct, gp)) hit++; });
      return { chunk: c, ct, hits: hit, overlap: hit / groups.length };
    });
    const kept = graded.filter(x => x.hits > 0 && (x.chunk.source !== 'data_sample' || x.overlap >= 0.34)).sort((a, b) => b.overlap - a.overlap);
    const best = kept.length ? kept[0].overlap : 0;
    const top3 = kept.slice(0, 3);
    const covered = groups.filter(gp => top3.some(k => sat(k.ct, gp))).length;
    const verdict = best >= CFG.cragMinOverlap ? 'correct' : best >= CFG.cragAmbiguous ? 'ambiguous' : 'incorrect';
    return { verdict, kept, coverage: covered / groups.length, best };
  }
  let _vocab = null;
  function vocab() {
    if (_vocab) return _vocab;
    const v = new Set(), cat = ensureCatalog();
    const addTerms = ts => ts.forEach(t => normWords(t).trim().split(' ').forEach(w => { if (w.length >= 3) v.add(w); }));
    cat.summary.forEach(s => addTerms(s.terms));
    cat.datasets.forEach(d => { addTerms(d.dimTerms); addTerms(d.dsTerms); d.measures.forEach(m => addTerms(m.terms)); });
    return (_vocab = v);
  }
  function fuzzyCorrect(raw) {
    const st = stem(raw), v = vocab();
    if (v.has(st) || st.length < 5) return raw;
    let best = raw, bs = 0;
    v.forEach(w => { const f = fuzzyScore(st, w); if (f > bs) { bs = f; best = w; } });
    return best;
  }
  function fuzzyCatalogSearch(rawTokens) {
    const cat = ensureCatalog(), res = [], tokens = rawTokens.map(stem);
    const consider = (id, label, terms) => {
      const words = new Set(); terms.forEach(t => normWords(t).trim().split(' ').forEach(w => { if (w.length >= 3) words.add(w); }));
      let s = 0;
      tokens.forEach(tk => { let best = 0; words.forEach(w => { const f = fuzzyScore(tk, w); if (f > best) best = f; }); s += best; });
      if (s > 0) res.push({ id, label, score: s });
    };
    cat.summary.forEach(x => consider(x.id, x.label, x.terms));
    cat.datasets.forEach(d => d.measures.forEach(m => consider(m.id, measureLabel(m, d), m.terms.concat(d.dimTerms))));
    return res.sort((a, b) => b.score - a.score);
  }
  async function rewriteQuery(prompt, round) {
    const raw = contentTokensRaw(expandAbbreviations(prompt));
    if (round === 1) {
      const exp = raw.slice(); raw.forEach(t => synFor(t).slice(0, 3).forEach(s => exp.push(s)));
      return { query: exp.join(' '), tokens: raw };
    }
    if (CFG.useLLM) {
      try {
        const kw = await llmFetch([{ role: 'system', content: "Réécris la demande en 3 à 6 mots-clés KPI financiers. Réponds uniquement par les mots-clés séparés par des espaces." }, { role: 'user', content: prompt }], false);
        const t = contentTokensRaw(kw);
        if (t.length) return { query: t.join(' '), tokens: raw.concat(t) };
      } catch (e) { }
    }
    const corr = raw.map(fuzzyCorrect);
    return corr.join(' ') !== raw.join(' ') ? { query: corr.join(' '), tokens: corr } : null;
  }
  async function cragRetrieve(prompt, ctxText) {
    const trace = [];
    const baseTokens = contentTokensRaw(expandAbbreviations(prompt));
    let chunks = RAGStore.search(expandAbbreviations(ctxText ? prompt + ' ' + ctxText : prompt), CFG.maxChunks * 2);
    let g = gradeChunks(tokenGroups(baseTokens), chunks);
    trace.push({ round: 0, verdict: g.verdict, retrieved: chunks.length, kept: g.kept.length, coverage: +g.coverage.toFixed(2) });
    for (let r = 1; r <= CFG.cragMaxRewrites && g.verdict !== 'correct'; r++) {
      const rw = await rewriteQuery(prompt, r); if (!rw) break;
      const seen = new Set(chunks.map(c => c.id));
      RAGStore.search(rw.query, CFG.maxChunks * 2).forEach(c => { if (!seen.has(c.id)) chunks.push(c); });
      g = gradeChunks(tokenGroups(rw.tokens), chunks);
      trace.push({ round: r, rewrite: rw.query, verdict: g.verdict, kept: g.kept.length, coverage: +g.coverage.toFixed(2) });
    }
    return { verdict: g.verdict, kept: g.kept.map(k => k.chunk).slice(0, CFG.maxChunks), graded: g.kept.slice(0, CFG.maxChunks * 2), trace, tokens: baseTokens };
  }

  /* ═══════════════════════ AGENTIC RAG ═══════════════════════ */
  const AgenticRAG = (function () {
    const Tools = {
      search_kpi(a) {
        const out = [], seen = new Set();
        RAGStore.search(String(a.query || ''), 10).forEach(c => {
          const id = c.meta.measureId || c.meta.summaryId;
          if (id && !seen.has(id)) { seen.add(id); out.push({ id, label: c.meta.label, dimension: c.meta.dimLabel || null }); }
        });
        return out.slice(0, 6);
      },
      fuzzy_search(a) { return fuzzyCatalogSearch(contentTokensRaw(String(a.query || ''))).slice(0, 6); },
      list_dimensions(a) {
        const f = findById(a.kpi_id); if (!f) return [];
        const fam = f.kind === 'summary' ? f.item.family : f.measure.family, out = [];
        ensureCatalog().datasets.forEach(d => { const m = d.measures.find(x => x.family === fam); if (m) out.push({ kpi_id: m.id, dimension: d.dimLabel, temporal: d.dimIsTime }); });
        return out;
      },
      inspect_values(a) {
        const d = ensureCatalog().datasets.find(x => x.key === a.dataset || x.measures.some(m => m.id === a.kpi_id));
        if (!d) return [];
        return [...new Set(d.rows.map(r => String(r[d.dim])))].slice(0, Number(a.limit) || 15);
      },
      check_chart(a) {
        const f = findById(a.kpi_id), issues = [];
        if (!f) return { ok: false, issues: ['KPI inconnu'] };
        if (f.kind === 'dataset') {
          if (a.chart_type === 'line' && !f.ds.dimIsTime) issues.push('dimension non temporelle pour une courbe');
          if (['pie', 'donut', 'treemap'].includes(a.chart_type) && f.ds.rows.some(r => Number(r[f.measure.name]) < 0)) issues.push('valeurs négatives dans un camembert');
        }
        return { ok: !issues.length, issues };
      }
    };
    function candidatesFrom(graded) {
      const score = new Map();
      const add = (id, s) => { if (id && findById(id)) score.set(id, (score.get(id) || 0) + s); };
      graded.forEach((g, i) => {
        const c = g.chunk, w = g.overlap + 1 / (i + 2);
        if (c.source === 'measure_meta') add(c.meta.measureId, w * 1.5);
        else if (c.source === 'summary_kpi') add(c.meta.summaryId, w);
        else if (c.source === 'dataset_schema' || c.source === 'data_sample') { const d = ensureCatalog().datasets.find(x => x.key === c.meta.datasetKey); if (d) add(d.measures[0].id, w * 0.4); }
      });
      return [...score.entries()].sort((a, b) => b[1] - a[1]).map(([id, s]) => ({ id, score: s }));
    }
    const confidentPick = (c, verdict) => c.length > 0 && verdict !== 'incorrect' && (c.length === 1 || c[0].score >= c[1].score * 1.35);
    async function llmLoop(prompt, trace) {
      const obs = [];
      const toolDoc = 'Outils : search_kpi{query}, fuzzy_search{query}, list_dimensions{kpi_id}, inspect_values{kpi_id|dataset,limit}, check_chart{kpi_id,chart_type}, final{kpi_ids:[],chart_type,top_n}';
      for (let step = 0; step < CFG.agentMaxSteps; step++) {
        const sys = "Tu es un agent BI. Réponds UNIQUEMENT par un JSON {\"tool\":\"nom\",\"args\":{}}. Termine avec tool=final. N'invente jamais d'id.\n" + toolDoc +
          '\nCatalogue :\n' + catalogLines(normWords(prompt)).split('\n').slice(0, 25).join('\n') + '\nÉtat : ' + stateSummary() +
          '\nObservations : ' + JSON.stringify(obs).slice(0, 1500);
        const raw = await llmFetch([{ role: 'system', content: sys }, { role: 'user', content: prompt }], true);
        const mm = raw.match(/\{[\s\S]*\}/); if (!mm) throw new Error('non-JSON');
        const j = JSON.parse(mm[0]);
        if (j.tool === 'final' || !Tools[j.tool]) {
          const ids = ((j.args && j.args.kpi_ids) || j.kpi_ids || []).filter(id => findById(id));
          trace.push({ agent: 'llm', step, final: ids });
          return ids;
        }
        const res = Tools[j.tool](j.args || {});
        obs.push({ tool: j.tool, args: j.args, result: res });
        trace.push({ agent: 'llm', step, tool: j.tool });
      }
      return [];
    }
    async function resolve(prompt, crag) {
      const trace = [];
      let cands = candidatesFrom(crag.graded || []);
      let source = 'crag';
      if (!cands.length) {
        const fz = Tools.fuzzy_search({ query: prompt }).filter(x => x.score >= 0.8);
        cands = fz.map(x => ({ id: x.id, score: x.score })); source = 'fuzzy';
        trace.push({ agent: 'det', tool: 'fuzzy_search', found: fz.length });
      }
      if (confidentPick(cands, crag.verdict) || (source === 'fuzzy' && cands.length && (cands.length === 1 || cands[0].score >= cands[1].score * 1.35))) {
        trace.push({ agent: 'det', picked: cands[0].id, source });
        return { ids: [cands[0].id], confident: true, candidates: cands.slice(0, CFG.clarifyOptions), trace, source };
      }
      if (CFG.useLLM && CFG.agentUseLLM) {
        try {
          const ids = await llmLoop(prompt, trace);
          if (ids.length) return { ids, confident: true, candidates: cands.slice(0, CFG.clarifyOptions), trace, source: 'llm-agent' };
        } catch (e) { trace.push({ agent: 'llm', failed: e.message }); }
      }
      return { ids: [], confident: false, candidates: cands.slice(0, CFG.clarifyOptions), trace, source };
    }
    return { resolve, Tools };
  })();

  function verifyIntent(intent, trace) {
    const g = intent.groups[0];
    if (!g || g.kind !== 'dataset' || !intent.legendFragment) return;
    const LP = normWords(intent.legendFragment);
    if (g.ds.dimTerms.some(t => has(LP, t))) return;
    const fam = g.measures[0].family;
    for (const d of ensureCatalog().datasets) {
      if (d.key === g.ds.key || !d.dimTerms.some(t => has(LP, t))) continue;
      const mm = d.measures.find(x => x.family === fam);
      if (mm) {
        intent.groups = [{ kind: 'dataset', ds: d, measures: [mm], score: 5 }];
        intent.notes.push(`Correction : la légende « ${intent.legendFragment} » correspond à la dimension « ${d.dimLabel} » → dataset ${d.key}.`);
        trace.push({ step: 'Verify', switchedTo: d.key });
        return;
      }
    }
  }

  /* ═══════════════════════ SPEC → CONFIG ═══════════════════════ */
  const isAdditive = k => k === 'money' || k === 'count';
  const FMT = (v, kind) => (root.Dashboard && root.Dashboard.formatValue) ? root.Dashboard.formatValue(v, kind) : String(v);

  function prepareRows(ds, measures, chartType, o) {
    const dim = ds.dim, first = measures[0].name, map = new Map();
    const comparison = o.comparison || null;

    if (comparison) {
      const rateField = comparison.rateField || first;
      const better = { [dim]: comparison.betterLabel, __n: 0 };
      const worse = { [dim]: comparison.worseLabel, __n: 0 };
      measures.forEach(m => { better[m.name] = 0; worse[m.name] = 0; });
      const fset0 = (o.filterValues && o.filterValues.length) ? new Set(o.filterValues.map(v => ascii(v).trim())) : null;
      ds.rows.forEach(r => {
        const raw = Number(r[rateField]);
        if (!isFinite(raw)) return;
        const key = String(r[dim]);
        if (fset0 && !fset0.has(ascii(key).trim())) return;
        // exclut le pays de référence
        if (comparison.baseline && ascii(key).trim() === ascii(comparison.baseline).trim()) return;
        const isBetter = raw > comparison.threshold;
        const target = isBetter ? better : worse;
        target.__n++;
        measures.forEach(m => {
          const v = Number(r[m.name]);
          if (isFinite(v)) target[m.name] += v;
        });
      });
      measures.forEach(m => {
        if (m.kind === 'percent' || m.kind === 'ratio') {
          better[m.name] = better.__n ? better[m.name] / better.__n : 0;
          worse[m.name] = worse.__n ? worse[m.name] / worse.__n : 0;
        }
      });
      // [CORRECTIF 7] nombre de pays par groupe (utilisé par le camembert)
      better.count = better.__n; worse.count = worse.__n;
      const out = [];
      if (better.__n > 0) out.push(better);
      if (worse.__n > 0) out.push(worse);
      delete better.__n; delete worse.__n;
      out.sort((a, b) => (a[dim] === comparison.betterLabel ? -1 : 1));
      return out;
    }

    const fset = (o.filterValues && o.filterValues.length) ? new Set(o.filterValues.map(v => ascii(v).trim())) : null;
    ds.rows.forEach(r => {
      if (!isFinite(Number(r[first]))) return;
      const k = String(r[dim]);
      if (fset && !fset.has(ascii(k).trim())) return;
      if (!map.has(k)) map.set(k, Object.assign({}, r, { __n: 1 }));
      else { const a = map.get(k); a.__n++; measures.forEach(me => { a[me.name] = (Number(a[me.name]) || 0) + (Number(r[me.name]) || 0); }); }
    });
    const rows = [...map.values()];
    rows.forEach(a => { if (a.__n > 1) measures.forEach(me => { if (me.kind === 'percent' || me.kind === 'ratio') a[me.name] = a[me.name] / a.__n; }); delete a.__n; });
    if (ds.dimIsTime) { rows.sort((a, b) => (a[dim] > b[dim]) - (a[dim] < b[dim])); return o.topN ? rows.slice(-o.topN) : rows; }
    rows.sort((a, b) => ((Number(b[first]) || 0) - (Number(a[first]) || 0)) * (o.sort === 'asc' ? -1 : 1));
    if (o.topN) return rows.slice(0, o.topN);
    if (o.allowOthers && ['pie', 'donut', 'treemap'].includes(chartType) && rows.length > CFG.pieMaxSlices && isAdditive(measures[0].kind)) {
      const head = rows.slice(0, CFG.pieMaxSlices), rest = rows.slice(CFG.pieMaxSlices), other = { [dim]: 'Autres' };
      measures.forEach(me => { other[me.name] = rest.reduce((s, r) => s + (Number(r[me.name]) || 0), 0); });
      return head.concat([other]);
    }
    return rows;
  }
  function inferChartType(intent, group) {
    if (intent.chartType) return intent.chartType;
    if (group.kind === 'summary') return 'card';
    if (group.ds.dimIsTime) return 'line';
    if (/(repartition|part\b|proportion|pourcentage|distribution|camembert)/.test(ascii(intent.text))) return 'pie';
    return 'bar';
  }
  function validateChart(t, ds, measures, intent, notes, explicit) {
    const r = { type: t, abs: false, autoTop: null, rank: false };
    if (t === 'line' && !ds.dimIsTime) {
      if (explicit) notes.push(`Courbe demandée : « ${ds.dimLabel} » n'est pas temporel.`);
      else { notes.push(`Courbe inadaptée → barres.`); r.type = 'bar'; }
    }
    if (t === 'scatter' && measures.length < 2) { notes.push('Nuage de points avec une seule mesure : axe X = rang.'); r.rank = true; }
    if (['pie', 'donut', 'treemap'].includes(t)) {
      const m0 = measures[0];
      if (ds.rows.some(r2 => Number(r2[m0.name]) < 0)) {
        if (explicit) { notes.push(`Valeurs négatives : valeurs absolues utilisées.`); r.abs = true; }
        else { notes.push(`Valeurs négatives → barres.`); r.type = 'bar'; }
      } else if (!isAdditive(m0.kind) && !intent.topN && !ds.dimIsTime && ds.rows.length > CFG.pieMaxSlices) {
        if (intent.comparison) {
          r.autoTop = null;
        } else if (explicit) {
          notes.push(`${ds.rows.length} catégories : lisibilité réduite.`);
        } else {
          r.autoTop = CFG.pieMaxSlices;
          notes.push(`Trop de catégories → top ${CFG.pieMaxSlices}.`);
        }
      }
    }
    if (intent.topN && ds.dimIsTime) notes.push(`Série temporelle : top ${intent.topN} = ${intent.topN} dernières périodes.`);
    if (intent.topN && !ds.dimIsTime && intent.topN > ds.rows.length) notes.push(`Il n'y a que ${ds.rows.length} éléments.`);
    return r;
  }

  function formatToMeta(f) {
    const meta = {}, style = {};
    if (f.barColor) { meta.barColor = f.barColor; meta.lineColor = f.barColor; meta.scatterColor = f.barColor; }
    if (f.dataLabels !== undefined) meta.showDataLabels = f.dataLabels;
    if (f.yMin !== undefined) meta.yAxisMin = f.yMin;
    if (f.yMax !== undefined) meta.yAxisMax = f.yMax;
    if (f.yInterval !== undefined) meta.yAxisInterval = f.yInterval;
    if (f.labelPosition) meta.labelPosition = f.labelPosition;
    if (f.labelFormat) meta.labelFormat = f.labelFormat;
    if (f.horizontal !== undefined) meta.horizontal = f.horizontal;
    if (f.legend !== undefined) meta.showLegend = f.legend;
    if (f.legendPosition) meta.legendPosition = f.legendPosition;
    if (f.categoryColors) meta.categoryColors = f.categoryColors;
    if (f.palette) meta.palette = f.palette;
    if (f.blur !== undefined) style.backdropFilter = 'blur(' + f.blur + 'px)';
    if (f.radius !== undefined) style.borderRadius = f.radius + 'px';
    if (f.shadow) style.boxShadow = SHADOWS[f.shadow] !== undefined ? SHADOWS[f.shadow] : SHADOWS.soft;
    if (f.background) {
      let resolved = BACKGROUNDS[f.background] || f.background;
      if (f.bgOpacity !== undefined) resolved = withAlpha(resolved, f.bgOpacity);
      style.backgroundColor = resolved;
    }
    if (f.borderWidth !== undefined) {
      style.borderWidth = typeof f.borderWidth === 'number' ? f.borderWidth + 'px' : f.borderWidth;
      style.borderStyle = f.borderStyle || 'solid';
      style.borderColor = f.borderColor || 'rgba(255, 255, 255, 0.15)';
      style.border = `${style.borderWidth} ${style.borderStyle} ${style.borderColor}`;
    }
    if (f.borderColor) {
      style.borderColor = f.borderColor;
      if (style.border) style.border = `${style.borderWidth || '1px'} ${style.borderStyle || 'solid'} ${style.borderColor}`;
    }
    return { meta, style };
  }

  function applyColors(cfg, f, rows, ds, chartType) {
    const cc = f.categoryColors || {}, hasCc = Object.keys(cc).length > 0;
    if (hasCc) {
      cfg.categoryColors = Object.assign({}, cfg.categoryColors || {}, cc);
    }
    const pal = f.palette && f.palette.length > 1 ? f.palette : null;
    const multi = ['pie', 'donut', 'treemap'].includes(chartType);
    if (!multi && !pal && !hasCc) return;
    const base = pal || (f.barColor && multi ? shades(f.barColor, rows.length) : null);
    if (!base && !hasCc) return;
    cfg.colors = rows.map((r, i) => {
      const key = String(r[ds.dim] || r.comparison || r.country || r.name || '');
      for (const [k, v] of Object.entries(cc)) {
        if (k.toLowerCase() === key.toLowerCase() || key.toLowerCase().includes(k.toLowerCase())) return v;
      }
      return (base ? base[i % base.length] : (f.barColor || DEFAULT_PALETTE[i % DEFAULT_PALETTE.length]));
    });
    if (pal) cfg.palette = pal;
    if (pal && cfg.series && cfg.series.length > 1) cfg.series = cfg.series.map((s, i) => Object.assign({}, s, { color: pal[i % pal.length] }));
  }

  /* ── SQL ── */
  const qi = s => '"' + String(s).replace(/"/g, '""') + '"';
  const ql = s => "'" + String(s).replace(/'/g, "''") + "'";
  const tableOf = key => CFG.sqlTableMap[key] || ((CFG.sqlSchema ? CFG.sqlSchema + '.' : '') + key);
  const aggSql = me => me.kind === 'count' ? 'COUNT(*)' : (me.kind === 'percent' || me.kind === 'ratio') ? `ROUND(AVG(${qi(me.name)}), 2)` : `SUM(${qi(me.name)})`;

  function genSql(group, o) {
    o = o || {};
    const type = o.chartType || 'bar';
    if (group.kind === 'summary') {
      const s = group.item, fn = (s.kind === 'percent' || s.kind === 'ratio') ? 'AVG' : 'SUM';
      return s.sql || `-- Apache Superset · KPI global\nSELECT ${fn}(${qi(s.key)}) AS ${qi(s.key)}\nFROM ${tableOf(CFG.summaryTable)};`;
    }
    if (o.comparison) {
      const c = o.comparison, ds = group.ds, m0 = group.measures[0];
      const rateCol = c.rateField || m0.name;
      return `-- Apache Superset · ${clean1(o.title || '')} · comparaison (baseline ${c.baseline})\n` +
        `SELECT CASE\n` +
        `         WHEN ${qi(rateCol)} > ${c.threshold} THEN ${ql(c.betterLabel)}\n` +
        `         ELSE ${ql(c.worseLabel)}\n` +
        `       END AS "comparison",\n` +
        `       COUNT(*) AS "count",\n` +
        `       ${group.measures.map(me => `${aggSql(me)} AS ${qi(me.name)}`).join(',\n       ')}\n` +
        `FROM ${tableOf(ds.key)}\n` +
        `WHERE ${qi(rateCol)} IS NOT NULL\n` +
        `  AND ${qi(ds.dim)} <> ${ql(c.baseline)}\n` +
        `GROUP BY 1\n` +
        `ORDER BY 1;`;
    }
    const ds = group.ds, filters = o.filterValues || [];
    const custom = group.measures.find(me => me.sql);
    if (custom && !o.topN && !filters.length && !(o.extraFilters || []).length) return custom.sql;
    const metrics = group.measures.map(me => `${aggSql(me)} AS ${qi(me.name)}`);
    const wh = [];
    if (filters.length) wh.push(`${qi(ds.dim)} IN (${filters.map(ql).join(', ')})`);
    (o.extraFilters || []).forEach(f => { if (ds.rows[0] && f.col in ds.rows[0]) wh.push(`${qi(f.col)} IN (${f.values.map(ql).join(', ')})`); });
    const where = wh.length ? '\nWHERE ' + wh.join('\n  AND ') : '';
    const head = `-- Apache Superset · ${clean1(o.title || '')} · graphique: ${type}\n`;
    const sel = `SELECT ${qi(ds.dim)} AS ${qi(ds.dim)},\n       ${metrics.join(',\n       ')}\nFROM ${tableOf(ds.key)}${where}\nGROUP BY ${qi(ds.dim)}`;
    if (ds.dimIsTime) {
      if (o.topN) return `${head}SELECT * FROM (\n${sel}\nORDER BY ${qi(ds.dim)} DESC\nLIMIT ${o.topN}\n) t\nORDER BY ${qi(ds.dim)} ASC;`;
      return `${head}${sel}\nORDER BY ${qi(ds.dim)} ASC;`;
    }
    const dir = o.sort === 'asc' ? 'ASC' : 'DESC';
    return `${head}${sel}\nORDER BY ${qi(group.measures[0].name)} ${dir}${o.topN ? `\nLIMIT ${o.topN}` : ''};`;
  }
  function supersetForm(group, o, cfg) {
    const VIZ = { bar: 'echarts_timeseries_bar', pie: 'pie', donut: 'pie', line: 'echarts_timeseries_line', scatter: 'echarts_timeseries_scatter', treemap: 'treemap_v2', card: 'big_number_total' };
    const type = cfg.chartType, f = o.format || {};
    const fd = { viz_type: VIZ[type] || 'echarts_timeseries_bar', row_limit: o.topN || 1000 };
    if (group.kind === 'summary') { fd.metric = group.item.key; return fd; }
    const ds = group.ds, names = cfg.series ? group.measures.map(m => m.name) : [];
    const multi = ['pie', 'donut', 'treemap'].includes(type);
    if (multi) { fd.groupby = [ds.dim]; fd.metric = names[0]; if (type === 'donut') { fd.donut = true; fd.innerRadius = 40; } }
    else { fd.x_axis = ds.dim; fd.metrics = names; }
    if (f.horizontal && type === 'bar') fd.orientation = 'horizontal';
    if (f.legend !== undefined) fd.show_legend = f.legend;
    if (f.legendPosition) fd.legendOrientation = f.legendPosition;
    if (f.dataLabels !== undefined) { fd.show_value = f.dataLabels; fd.show_labels = f.dataLabels; }
    const lc = {};
    if (multi && cfg.colors && cfg.data) cfg.data.forEach((r, i) => { lc[String(r[ds.dim])] = cfg.colors[i]; });
    if (!multi && f.barColor) names.forEach(n => { lc[n] = f.barColor; });
    if (Object.keys(lc).length) fd.label_colors = lc;
    return fd;
  }
  function genDax(group, o) {
    if (group.kind === 'summary') { const s = group.item; return s.dax || (`-- DAX Power BI\nTotal ${humanize(s.key)} = SUM('Active Dataset'[${s.family}])`); }
    const ds = group.ds, topN = o && o.topN;
    return (topN ? `-- DAX avec Top ${topN}\n` : '-- DAX Power BI\n') + group.measures.map(me => {
      if (me.dax) return me.dax;
      const fn = (me.kind === 'percent' || me.kind === 'ratio') ? 'AVERAGE' : 'SUM';
      const base = `${humanize(me.name)} = ` + (me.kind === 'count' ? `COUNTROWS('${ds.key}')` : `${fn}('${ds.key}'[${me.name}])`);
      return topN ? `${base}\nTop ${topN} ${humanize(me.name)} = CALCULATE([${humanize(me.name)}], TOPN(${topN}, ALL('${ds.key}'[${ds.dim}]), [${humanize(me.name)}], DESC))` : base;
    }).join('\n\n');
  }

  function summaryConfig(group, intent, fmtMeta, spec) {
    const s = group.item, store = root.BI_DATA_STORE || {};
    let v = 0;
    if (s.raw_value !== undefined && s.raw_value !== null) {
      v = s.raw_value;
    } else if (s.value !== undefined && s.value !== null) {
      v = s.value;
    } else if (store.summary && store.summary[s.key] !== undefined) {
      v = store.summary[s.key];
    } else {
      const cat = root.KPIS_CATALOG || {};
      const kpiMatch = (cat.kpis || []).find(k => k.id === s.id || k.id === s.key || (k.name && k.name.toLowerCase() === (s.label || '').toLowerCase()));
      if (kpiMatch && (kpiMatch.raw_value !== undefined || kpiMatch.current_value !== undefined)) {
        v = kpiMatch.raw_value !== undefined ? kpiMatch.raw_value : kpiMatch.current_value;
      } else {
        for (const tName of Object.keys(store)) {
          const rows = store[tName];
          if (Array.isArray(rows) && rows.length > 0) {
            const col = s.name || s.key || s.family || (s.terms && s.terms[0]);
            const rowKeys = Object.keys(rows[0]);
            const matchedCol = rowKeys.find(c => c.toLowerCase() === String(col).toLowerCase() || c.toLowerCase().includes(String(col).toLowerCase()));
            if (matchedCol) {
              const nums = rows.map(r => parseFloat(String(r[matchedCol]).replace(/[^0-9.-]+/g, ''))).filter(isFinite);
              if (nums.length) {
                const avg = (s.kind === 'percent' || s.kind === 'ratio');
                v = nums.reduce((a, b) => a + b, 0) / (avg ? nums.length : 1);
                break;
              }
            }
          }
        }
      }
    }
    if (s.kind === 'percent' && /roe|margin|yield/.test(s.key) && Math.abs(v) <= 2) v = v * 100;
    const formatted = s.current_value_formatted || FMT(v, s.kind === 'number' ? 'auto' : s.kind);
    const title = intent.title || s.label;
    const cfg = Object.assign({
      title, subtitle: 'Indicateur global', chartType: 'card', domain: 'MESURE', metricLabel: s.label, cardValue: v,
      cardValueFormatted: formatted, cardBenchmark: s.description || 'Mesure directe', dax: genDax(group, intent)
    }, fmtMeta);
    cfg.sql = genSql(group, { title, chartType: 'card' });
    cfg.superset = supersetForm(group, { format: (spec && spec.format) || {} }, cfg);
    return cfg;
  }

  function datasetConfig(group, intent, fmtMeta, notes, spec) {
    const ds = group.ds, f = (spec && spec.format) || intent.format || {};
    let measures = group.measures.slice();
    const explicit = !!intent.chartExplicit && CFG.forceExplicitChartType;
    let chartType = inferChartType(intent, group);
    if (chartType === 'scatter' && measures.length < 2) {
      const other = ds.measures.find(me => me !== measures[0]);
      if (other) measures.push(other);
    }
    const v = validateChart(chartType, ds, measures, intent, notes, explicit);
    chartType = v.type;
    if (['pie', 'donut', 'treemap'].includes(chartType) && measures.length > 1) { notes.push(`Une seule mesure : « ${measures[0].label} ».`); measures = [measures[0]]; }
    const g = Object.assign({}, group, { measures });
    const labels = measures.map(me => me.label);
    const topN = intent.topN || v.autoTop || null;
    const filterValues = intent.filterValues || [];

    if (chartType === 'card') {
      const m0 = measures[0];
      const fs = filterValues.length ? new Set(filterValues.map(x => ascii(x).trim())) : null;
      const vals = ds.rows.filter(r => !fs || fs.has(ascii(String(r[ds.dim])).trim())).map(r => {
        const raw = r[m0.name];
        return typeof raw === 'number' ? raw : parseFloat(String(raw).replace(/[^0-9.-]+/g, ''));
      }).filter(isFinite);
      const avg = (m0.kind === 'percent' || m0.kind === 'ratio'), val = vals.length ? (vals.reduce((a, b) => a + b, 0) / (avg ? (vals.length || 1) : 1)) : 0;
      const title = intent.title || (avg ? `${m0.label} (moyenne)` : `${m0.label} (total)`);
      const cfg = Object.assign({
        title, subtitle: `Dataset: ${ds.key}`, chartType: 'card', domain: 'MESURE', metricLabel: m0.label,
        cardValue: val, cardValueFormatted: FMT(val, m0.kind === 'number' ? 'auto' : m0.kind), cardBenchmark: `${avg ? 'moyenne' : 'somme'} sur ${vals.length} lignes`, dax: genDax(g, { topN })
      }, fmtMeta);
      const agg = `${avg ? 'AVG' : 'SUM'}(${qi(m0.name)})`;
      cfg.sql = `-- Apache Superset · ${clean1(title)} · card\nSELECT ${agg} AS ${qi(m0.name)}\nFROM ${tableOf(ds.key)}` + (filterValues.length ? `\nWHERE ${qi(ds.dim)} IN (${filterValues.map(ql).join(', ')})` : '') + ';';
      cfg.superset = { viz_type: 'big_number_total', metric: m0.name };
      return cfg;
    }

    const rows = prepareRows(ds, measures, chartType, {
      topN, sort: intent.sort, filterValues,
      allowOthers: !intent.comparison && !explicit && !intent.topN && !filterValues.length,
      comparison: intent.comparison || null
    });
    if (!rows.length) throw new Error('Dataset vide — aucune donnée exploitable.');
    if (v.abs) rows.forEach(r => measures.forEach(me => { r[me.name] = Math.abs(Number(r[me.name]) || 0); }));
    const pre = (topN && !ds.dimIsTime) ? `Top ${topN} — ` : '';
    const fsuf = (filterValues.length && filterValues.length <= 4) ? ` (${filterValues.join(', ')})` : '';
    const title = intent.title || (intent.comparison
      ? `Répartition : ${intent.comparison.betterLabel} vs ${intent.comparison.worseLabel}`
      : (ds.dimIsTime ? `Évolution : ${labels.join(', ')}${fsuf}` : `${pre}${labels.join(' & ')} par ${ds.dimLabel}${fsuf}`));
    // [CORRECTIF 7] comparaison → on affiche le NOMBRE de pays (champ count)
    const cfg = Object.assign({
      title, subtitle: `Dataset: ${ds.key} | ${labels.join(', ')}`, chartType, domain: ds.key.replace(/_/g, ' ').toUpperCase().slice(0, 14),
      data: rows, labelField: ds.dim,
      valueField: intent.comparison ? 'count' : measures[0].name,
      metricLabel: intent.comparison ? 'Nombre de pays' : measures[0].label,
      valueFormat: intent.comparison ? 'count' : (measures[0].kind === 'number' ? 'auto' : measures[0].kind),
      series: intent.comparison ? [{ name: 'Nombre de pays', field: 'count' }] : measures.map(me => ({ name: me.label, field: me.name })),
      dax: genDax(g, { topN }),
      comparison: intent.comparison || null
    }, fmtMeta);
    if (chartType === 'scatter') {
      if (v.rank) { rows.forEach((r, i) => { r.__rank = i + 1; }); cfg.xField = '__rank'; cfg.xName = 'Rang'; cfg.yField = measures[0].name; cfg.yName = measures[0].label; }
      else { cfg.xField = measures[0].name; cfg.yField = measures[1].name; cfg.xName = measures[0].label; cfg.yName = measures[1].label; }
    }
    applyColors(cfg, f, rows, ds, chartType);
    const sqlOpts = { topN, sort: intent.sort, filterValues, chartType, title, format: f, comparison: intent.comparison || null, extraFilters: intent.extraFilters || [] };
    cfg.sql = genSql(g, sqlOpts);
    cfg.superset = supersetForm(g, sqlOpts, cfg);
    return cfg;
  }

  /* ═══════════════════════ SPEC ═══════════════════════ */
  function newSpec(group) {
    return {
      sid: uid('v_'), kind: group.kind, measureIds: group.measures.map(m => m.id), chartType: null, chartExplicit: false,
      topN: null, sort: null, title: null, format: {}, filterValues: [], legendFragment: null, comparison: null, prompt: '', history: [], extraFilters: [], createdAt: Date.now()
    };
  }
  function groupOfSpec(spec) { return groupsFromIds(spec.measureIds)[0] || null; }

  function mergeFormat(a, b) {
    const r = Object.assign({}, a);
    Object.keys(b || {}).forEach(k => {
      if (b[k] === null || b[k] === undefined) { delete r[k]; return; }
      if (k === 'categoryColors' && r[k]) r[k] = Object.assign({}, r[k], b[k]); else r[k] = b[k];
    });
    return r;
  }
  function detectFilterValues(intent, ds) {
    if (intent.comparison) return [];
    if (!(intent.legendFragment || intent.filterCue)) return [];
    const T = intent.textAscii || ascii(intent.text);
    if ((intent.colorMentions || []).length && !/(seulement|uniquement|only|filtr|garde|parmi|entre)/.test(T)) return [];
    const labels = [...new Set(ds.rows.map(r => String(r[ds.dim])))];
    return labels.filter(lb => { const a = ascii(lb).trim(); return a.length >= 2 && new RegExp('(?:^|[^a-z0-9])' + escRe(a) + '(?:$|[^a-z0-9])').test(T); });
  }
  function labelForms(lb) {
    const base = ascii(lb).trim(), forms = new Set([base]);
    Object.entries(COUNTRY_SYNONYMS).forEach(([canon, syns]) => {
      const all = [canon].concat(syns).map(s => ascii(s).trim());
      if (all.includes(base)) all.forEach(s => { if (s.length >= 3) forms.add(s); });
    });
    return [...forms].filter(f => f.length >= 2);
  }
  function resolveColors(intent, ds, labelsIn) {
    const T = intent.textAscii || ascii(intent.text), mentions = intent.colorMentions || [];
    const labels = labelsIn || (ds && ds.rows ? [...new Set(ds.rows.map(r => String(r[ds.dim])))] : []);
    const hits = [];
    labels.forEach(lb => labelForms(lb).forEach(f => {
      const re = new RegExp('(?:^|[^a-z0-9])(' + escRe(f) + ')(?=$|[^a-z0-9])', 'g'); let m;
      while ((m = re.exec(T)) !== null) { const s = m.index + m[0].length - m[1].length; hits.push({ lb, s, e: s + f.length }); }
    }));
    const cat = {}, generic = [];
    mentions.forEach(mn => {
      let best = null, bd = 999;
      hits.forEach(h => {                       // « X en rouge » préféré à « rouge pour X »
        const d = (h.e <= mn.idx ? mn.idx - h.e : h.s - mn.idx + 6);
        if (d < bd) { bd = d; best = h; }
      });
      if (best && bd <= 40) cat[best.lb] = mn.hex; else generic.push(mn.hex);
    });
    const g = [...new Set(generic)], out = {};
    if (Object.keys(cat).length) out.categoryColors = cat;                       // élément(s) ciblé(s) uniquement
    else if (/\b(?:element|tranche|part|portion|section)\b|dans la legende/.test(T)) out._unresolved = labels.slice(0, 12);
    else if (g.length) { out.barColor = g[0]; out.palette = g.length > 1 ? g : null; out.categoryColors = null; }
    return out;
  }

  function applyIntentToSpec(spec, intent, notes) {
    const done = [], isNew = !spec.prompt;
    if (isNew) spec.prompt = intent.text;
    spec.history.push(intent.text); if (spec.history.length > 20) spec.history.shift();
    if (!isNew && intent.groups.length) {
      const g = intent.groups[0], ids = g.measures.map(m => m.id);
      if (ids.join() !== spec.measureIds.join()) {
        spec.measureIds = ids; spec.kind = g.kind; spec.filterValues = [];
        done.push('mesure → ' + g.measures.map(m => m.label).join(', ') + (g.ds ? ' par ' + g.ds.dimLabel : ''));
      }
    }
    if (intent.chartExplicit && intent.chartType) {
      if (intent.chartType !== spec.chartType) done.push('type → ' + intent.chartType);
      spec.chartType = intent.chartType; spec.chartExplicit = true;
    } else if (isNew && intent.chartType) spec.chartType = intent.chartType;
    if (intent.clearTop && spec.topN) { done.push(`top ${spec.topN} retiré`); spec.topN = null; }
    else if (intent.topN != null && intent.topN > 0 && intent.topN !== spec.topN) { done.push(spec.topN ? `top ${spec.topN} → top ${intent.topN}` : `top ${intent.topN}`); spec.topN = intent.topN; }
    if (intent.sort && intent.sort !== spec.sort) { spec.sort = intent.sort; done.push('tri ' + (intent.sort === 'asc' ? 'croissant' : 'décroissant')); }
    if (intent.title && intent.title !== spec.title) { spec.title = intent.title; done.push('titre « ' + intent.title + ' »'); }
    if (intent.legendFragment) spec.legendFragment = intent.legendFragment;
    const group = groupOfSpec(spec);
    if (intent.clearTop) spec.filterValues = [];

    if (intent.comparison && group && group.kind === 'dataset') {
      spec.comparison = intent.comparison;
      spec.format = mergeFormat(spec.format, {
        categoryColors: {
          [intent.comparison.betterLabel]: intent.comparison.colorBetter,
          [intent.comparison.worseLabel]: intent.comparison.colorWorse
        }
      });
      if (!spec.format.labelPosition) {
        spec.format = mergeFormat(spec.format, { labelPosition: 'outside', labelFormat: 'both' });
      }
      done.push(`comparaison ${intent.comparison.betterLabel} (${intent.comparison.colorBetter}) / ${intent.comparison.worseLabel} (${intent.comparison.colorWorse})`);
      if (intent.comparison.fallback === 'gdp') {
        notes.push(`⚠️ Pas de taux de change pour "${intent.comparison.baseline}" → comparaison sur le PIB.`);
      }
    }

    if (group && group.kind === 'dataset') {
      const fv = detectFilterValues(intent, group.ds);
      if (fv.length) { spec.filterValues = fv; done.push('légende/filtre : ' + fv.join(', ')); }
    }
    const fin = Object.assign({}, intent.format);

    // ── [CORRECTIF 7bis] Couleurs sur un visuel de comparaison existant ──
    const activeComp = spec.comparison || (intent.comparison && !intent.comparison.partialCue ? intent.comparison : null);
    if ((intent.colorMentions || []).length && group && group.kind === 'dataset' && !intent.comparison) {
      if (activeComp) {
        const T = intent.textAscii || ascii(intent.text);
        const parsed = parseColors(T);
        const catUpdate = {};
        const betterMentioned = /meilleur|mieux|plus (?:fort|haut|grand|elev)|superieur/.test(T);
        const worseMentioned = /pire|moins|plus faible|inferieur/.test(T);
        if (betterMentioned && parsed.list.length >= 1) catUpdate[activeComp.betterLabel] = parsed.list[0];
        if (worseMentioned && parsed.list.length >= (betterMentioned ? 2 : 1)) catUpdate[activeComp.worseLabel] = parsed.list[betterMentioned ? 1 : 0];
        if (!betterMentioned && !worseMentioned && parsed.list.length >= 1) {
          catUpdate[activeComp.betterLabel] = parsed.list[0];
          if (parsed.list[1]) catUpdate[activeComp.worseLabel] = parsed.list[1];
        }
        if (Object.keys(catUpdate).length) {
          fin.categoryColors = catUpdate;
          if (catUpdate[activeComp.betterLabel]) spec.comparison.colorBetter = catUpdate[activeComp.betterLabel];
          if (catUpdate[activeComp.worseLabel]) spec.comparison.colorWorse = catUpdate[activeComp.worseLabel];
          delete fin.barColor; delete fin.palette;
        }
      } else {
        // Visuel normal (pas de comparaison)
        const rc = resolveColors(intent, group.ds);
        delete fin.barColor; delete fin.palette;
        if (rc._unresolved) { notes.push('Élément introuvable dans la légende. Valeurs disponibles : ' + rc._unresolved.join(', ')); delete rc._unresolved; }
        Object.assign(fin, rc);
      }
    }

    const before = JSON.stringify(spec.format);
    spec.format = mergeFormat(spec.format, fin);
    if (JSON.stringify(spec.format) !== before) { const d = describeFormat(fin); if (d) done.push(d); }
    return done;
  }
  function buildFromSpec(spec, notes) {
    let group = groupOfSpec(spec);
    if (!group) throw new Error('Dataset introuvable ou vide.');
    if (spec.extraFilters && spec.extraFilters.length && group.kind === 'dataset') {
      const rowsF = group.ds.rows.filter(r => spec.extraFilters.every(f => !(f.col in r) || f.values.some(v => normV(v) === normV(r[f.col]))));
      if (!rowsF.length) throw new Error('Dataset vide — aucun résultat pour ce filtre.');
      group = Object.assign({}, group, { ds: Object.assign({}, group.ds, { rows: rowsF }) });
    }
    const { meta, style } = formatToMeta(spec.format);
    const pseudo = { text: spec.prompt, topN: spec.topN, sort: spec.sort, title: spec.title, chartType: spec.chartType, chartExplicit: spec.chartExplicit, filterValues: spec.filterValues, format: spec.format, comparison: spec.comparison || null, extraFilters: spec.extraFilters || [] };
    const cfg = group.kind === 'summary' ? summaryConfig(group, pseudo, meta, spec) : datasetConfig(group, pseudo, meta, notes, spec);
    cfg._agentSid = spec.sid;
    ['palette', 'colors', 'categoryColors', 'barColor', 'lineColor', 'scatterColor'].forEach(k => { if (!(k in cfg)) cfg[k] = undefined; });
    return { cfg, style, group };
  }

  function describeFormat(f) {
    if (!f) return '';
    const p = [];
    if (f.palette && f.palette.length) p.push('palette ' + f.palette.join(' / '));
    else if (f.barColor) p.push('couleur ' + f.barColor);
    if (f.categoryColors) p.push('couleurs par catégorie : ' + Object.keys(f.categoryColors).map(k => `${k}=${f.categoryColors[k]}`).join(', '));
    if (f.dataLabels !== undefined) p.push(f.dataLabels ? 'étiquettes affichées' : 'étiquettes masquées');
    if (f.legend !== undefined) p.push(f.legend ? 'légende visible' : 'légende masquée');
    if (f.legendPosition) p.push('légende ' + f.legendPosition);
    if (f.yMin !== undefined) p.push('axe Y min ' + f.yMin);
    if (f.yMax !== undefined) p.push('axe Y max ' + f.yMax);
    if (f.yInterval !== undefined) p.push('pas ' + f.yInterval);
    if (f.blur !== undefined) p.push('flou ' + f.blur + 'px');
    if (f.radius !== undefined) p.push('arrondi ' + f.radius + 'px');
    if (f.borderWidth !== undefined) p.push('bordure ' + f.borderWidth + (typeof f.borderWidth === 'number' ? 'px' : ''));
    if (f.borderColor) p.push('bordure couleur ' + f.borderColor);
    if (f.shadow) p.push('ombre ' + f.shadow);
    if (f.background) p.push('fond ' + f.background);
    if (f.horizontal !== undefined) p.push(f.horizontal ? 'barres horizontales' : 'barres verticales');
    if (f.labelPosition && f.dataLabels === undefined) p.push('étiquettes ' + f.labelPosition);
    return p.join(', ');
  }
  function suggestFor(chartType, group) {
    const s = [];
    if (group && group.kind === 'dataset') {
      if (!group.ds.dimIsTime) { s.push('Top 5 seulement'); s.push(chartType === 'pie' ? 'Passe-le en barres' : 'Mets-le en camembert'); }
      else s.push('Montre-le en barres');
      s.push('Change la couleur en vert'); s.push('Affiche les étiquettes');
    } else { s.push('Montre le Market Cap par secteur'); s.push('Quels KPI sont disponibles ?'); }
    s.push('Explique ce visuel');
    return s.slice(0, 4);
  }
  const sqlBlock = sqls => '\n\n🧾 **SQL Apache Superset :**\n```sql\n' + sqls.join('\n\n') + '\n```';

  /* ═══════════════════════ EXÉCUTION ═══════════════════════ */
  class NoActiveVisual extends Error { }

  function recreate(D, item, cfg, style) {
    try { D.removeVisual(item.id); } catch (e) { }
    const id = D.addVisual(cfg);
    if (!id) throw new Error('Le Dashboard a refusé de recréer le visuel.');
    if (style && Object.keys(style).length && D.updateVisual) D.updateVisual(id, {}, style);
    return id;
  }

  function legacyUpdate(id, intent, out, notes, D) {
    const { meta, style } = formatToMeta(intent.format);
    if (intent.title) meta.title = intent.title;
    const done = []; let t = null;
    const reg = D.getRegistry ? D.getRegistry() : {};
    const regEntry = reg[id];
    if ((intent.colorMentions || []).length && regEntry && regEntry.config && Array.isArray(regEntry.config.data) && regEntry.config.data.length) {
      const c0 = regEntry.config, lf = c0.labelField || Object.keys(c0.data[0])[0];
      const rc = resolveColors(intent, null, c0.data.map(r => String(r[lf])));
      if (rc.categoryColors || rc._unresolved) { delete meta.barColor; delete meta.lineColor; delete meta.scatterColor; delete meta.palette; }
      if (rc.categoryColors) { meta.categoryColors = Object.assign({}, c0.categoryColors || {}, rc.categoryColors); done.push('couleurs par élément : ' + Object.keys(rc.categoryColors).join(', ')); }
      else if (rc._unresolved) notes.push('Élément introuvable. Valeurs : ' + rc._unresolved.join(', '));
    }

    // ── Filtre par filterValues sur un visuel existant ──
    if (intent.filterValues && intent.filterValues.length && regEntry && regEntry.config) {
      const cfg = regEntry.config;
      const rawData = cfg._rawOriginalData || cfg.data;
      if (rawData && rawData.length) {
        if (!cfg._rawOriginalData) cfg._rawOriginalData = rawData.slice();
        const labelField = cfg.labelField || Object.keys(rawData[0] || {})[0];
        const allLabels = rawData.map(r => String(r[labelField] || ''));
        const matched = [];
        intent.filterValues.forEach(fv => {
          const resolved = matchCountryLabel(fv, allLabels);
          if (resolved && !matched.includes(resolved)) matched.push(resolved);
          else {
            const direct = allLabels.find(lb => ascii(lb).includes(ascii(fv)) || ascii(fv).includes(ascii(lb)));
            if (direct && !matched.includes(direct)) matched.push(direct);
          }
        });
        if (matched.length) {
          const filtered = rawData.filter(r => matched.includes(String(r[labelField] || '')));
          if (filtered.length) {
            meta.data = filtered;
            done.push('filtré sur : ' + matched.join(', '));
          } else {
            notes.push('Aucun élément trouvé pour le filtre : ' + intent.filterValues.join(', '));
          }
        } else {
          notes.push('Valeurs de filtre non reconnues dans ce visuel : ' + intent.filterValues.join(', '));
        }
      }
    }

    // ── Mise à jour de la comparaison (baseline swap sur visuel legacy) ──
    if (intent.comparison && regEntry && regEntry.config) {
      meta.comparison = intent.comparison;
      meta.categoryColors = {
        [intent.comparison.betterLabel]: intent.comparison.colorBetter,
        [intent.comparison.worseLabel]: intent.comparison.colorWorse
      };
      done.push(`comparaison ${intent.comparison.betterLabel} / ${intent.comparison.worseLabel}`);
    }

    const hasOnlyFormatChanges = !intent.chartExplicit && !intent.groups.length && !intent.topN && !intent.filterValues;
    const safeToChangeType = intent.chartExplicit && intent.chartType && !hasOnlyFormatChanges;
    if (safeToChangeType && D.changeChartType) {
      if (D.changeChartType(id, intent.chartType)) { done.push('type → ' + intent.chartType); t = intent.chartType; }
      else notes.push('Changement de type non applicable.');
    }
    if (intent.format && intent.format.horizontal !== undefined) meta.horizontal = intent.format.horizontal;
    if (intent.format && intent.format.categoryColors) meta.categoryColors = Object.assign(meta.categoryColors || {}, intent.format.categoryColors);
    if (Object.keys(meta).length || Object.keys(style).length) D.updateVisual(id, meta, style);
    const d = describeFormat(intent.format); if (d) done.push(d);
    if (intent.topN !== null) notes.push("Ce visuel n'a pas été créé par l'agent : le top N ne peut pas être recalculé.");
    return out(done.length ? '🎨 Visuel mis à jour : ' + done.join(' · ') + '.' : "Je n'ai rien compris à modifier — essaie : « mets en rouge » ou « filtre sur France, Italy ».", { chartType: t });
  }

  function dataSignature(c) {
    if (!c) return '';
    return JSON.stringify({
      ct: c.chartType,
      data: (c.data || []).map(r => String(r[c.labelField]) + '|' + String(r[c.valueField])),
      series: (c.series || []).map(s => s.name + ':' + s.field),
      lf: c.labelField, vf: c.valueField, ml: c.metricLabel,
      t: c.title, cv: c.cardValue, xf: c.xField, yf: c.yField,
      comp: c.comparison ? c.comparison.betterLabel + '/' + c.comparison.worseLabel : ''
    });
  }

  /* ── Persistance Backend des visuels créés par prompt ── */
  function syncVisualToBackend(entry) {
    if (!ORIGIN) return;
    const payload = { visual: { sid: entry.sid, spec: entry.spec, cfg: entry.cfg, style: entry.style } };
    fetch(ORIGIN + '/api/agent/visuals/prompt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).catch(e => console.warn('[BIAgent] syncVisualToBackend failed:', e));
  }

  function deleteVisualFromBackend(sid) {
    if (!ORIGIN || !sid) return;
    fetch(ORIGIN + '/api/agent/visuals/prompt/' + encodeURIComponent(sid), {
      method: 'DELETE'
    }).catch(e => console.warn('[BIAgent] deleteVisualFromBackend failed:', e));
  }

  function deleteVisual(idOrSid) {
    if (!idOrSid) return false;
    const it = Visuals.items.find(v => v.sid === idOrSid || v.id === idOrSid);
    const sid = it ? it.sid : (typeof idOrSid === 'string' && idOrSid.startsWith('v_') ? idOrSid : null);
    if (it) {
      Visuals.remove(it.sid);
    }
    if (sid) {
      deleteVisualFromBackend(sid);
      if (Memory.state.activeSid === sid) {
        Memory.state.activeSid = Visuals.count() ? Visuals.items[Visuals.count() - 1].sid : null;
        Memory.save();
      }
      return true;
    }
    return false;
  }

  function syncVisualFromDashboard(sid, cfg, containerStyle) {
    if (!sid) return;
    const it = Visuals.bySid(sid);
    if (it) {
      it.cfg = Object.assign({}, it.cfg, cfg);
      it.style = Object.assign({}, it.style, containerStyle);
      Visuals.persist();
      syncVisualToBackend(it);
    }
  }

  const normV = v => ascii(String(v)).trim();

  function findFilterSpec(text) {
    const T = ascii(normalizeTypos(text)).replace(/_/g, ' '), found = [];
    ensureCatalog().datasets.forEach(d => {
      if (!d.rows.length) return;
      Object.keys(d.rows[0]).forEach(col => {
        const vals = [...new Set(d.rows.map(r => r[col]).filter(v => v !== null && v !== undefined && v !== '').map(String))];
        if (vals.length < 2 || vals.length > 500) return;
        const colMentioned = new RegExp('\\b' + escRe(ascii(col).replace(/_/g, ' ')) + '\\b').test(T);
        const isNum = typeof d.rows[0][col] === 'number';
        let hits = vals.filter(v => { const a = normV(v); return a.length >= 2 && new RegExp('(?:^|[^a-z0-9])' + escRe(a) + '(?:$|[^a-z0-9])').test(T); });
        if (isNum && !colMentioned && !isTimeName(col)) hits = [];
        if (!hits.length && /country|pays/i.test(col))
          T.split(/[\s,;]+/).forEach(w => { const m = matchCountryLabel(w, vals); if (m && !hits.includes(m)) hits.push(m); });
        if (hits.length) found.push({ col, values: hits, score: hits.length + (colMentioned ? 3 : 0) + (isNum ? 0 : 1) });
      });
    });
    found.sort((a, b) => b.score - a.score);
    return found[0] || null;
  }

  function pushSpec(D, it) {
    const b = buildFromSpec(it.spec, []);
    D.updateVisual(it.id, b.cfg, b.style);
    Visuals.update(it.spec.sid, { cfg: b.cfg, style: b.style, spec: it.spec });
    syncVisualToBackend({ sid: it.spec.sid, spec: it.spec, cfg: b.cfg, style: b.style });
  }

  function applyGlobalFormat(D, f) {
    const reg = D.getRegistry ? D.getRegistry() : {}, { meta, style } = formatToMeta(f), agentIds = new Set();
    Visuals.items.forEach(it => {
      if (!it.spec || !reg[it.id]) return;
      agentIds.add(it.id);
      const fin = Object.assign({}, f);
      if ((fin.barColor || fin.palette) && !it.spec.comparison) fin.categoryColors = null;
      try { it.spec.format = mergeFormat(it.spec.format, fin); pushSpec(D, it); }
      catch (e) { console.warn('[BIAgent] global format', it.id, e); }
    });
    if (D.applyGlobalMeta) D.applyGlobalMeta(meta, agentIds);      // visuels auto-générés (sans spec)
    if (D.applyGlobalStyle && Object.keys(style).length) D.applyGlobalStyle(style);
    return Object.keys(reg).length;
  }

  function applyGlobalDataFilter(D, intent) {
    const fs = findFilterSpec(intent.text), reg = D.getRegistry ? D.getRegistry() : {};
    let ok = 0, skipped = 0, empty = 0;
    // 1) visuels créés par prompt (spec) : inchangé
    Visuals.items.forEach(it => {
      if (!it.spec || !reg[it.id] || it.spec.kind !== 'dataset') return;
      const prevEF = it.spec.extraFilters, prevTop = it.spec.topN;
      try {
        if (fs) {
          const g = groupOfSpec(it.spec);
          if (!g || !g.ds.rows[0] || !(fs.col in g.ds.rows[0])) { skipped++; return; }
          it.spec.extraFilters = (it.spec.extraFilters || []).filter(x => x.col !== fs.col).concat([fs]);
        }
        if (intent.topN) it.spec.topN = intent.topN;
        pushSpec(D, it); ok++;
      } catch (e) { it.spec.extraFilters = prevEF; it.spec.topN = prevTop; empty++; }
    });
    // 2) visuels automatiques : asynchrone (SQL serveur)
    filterAutoVisuals(D, intent, fs);
    return { message: `🔍 ${ok} visuel(s) créé(s) par prompt mis à jour (${skipped} ignoré(s), ${empty} sans résultat). Les visuels automatiques sont filtrés côté serveur…` };
  }

  async function filterAutoVisuals(D, intent, fsClient) {
    const reg = D.getRegistry ? D.getRegistry() : {};
    let fs = null;
    try {
      const r = await fetch((ORIGIN || '') + '/api/agent/detect-filter', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: intent.text })
      });
      fs = (await r.json()).filter || null;
    } catch (e) { }
    fs = fs || fsClient;
    const topN = intent.topN || null;
    if (!fs && !topN) {
      if (root.Agent && root.Agent._appendMessage) root.Agent._appendMessage('agent', "🔍 Aucune valeur de filtre reconnue. Ex : « filtre tous les visuels sur France ».");
      return;
    }
    let n = 0;
    await Promise.all(Object.keys(reg).map(async id => {
      const c = reg[id].config;
      if (Visuals.byId(id) || !c || c.chartType === 'card' || c.chartType === 'kpi_card' || !Array.isArray(c.data)) return;
      if (!c._rawOriginalData) c._rawOriginalData = c.data.slice();
      let rows = null;
      if (fs && c.sql) {
        c._gf = (c._gf || []).filter(x => x.col !== fs.col).concat([{ col: fs.col, values: fs.values }]);
        try {
          const res = await (await fetch((ORIGIN || '') + '/api/agent/filter-sql', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sql: c.sql, filters: c._gf })
          })).json();
          if (res.applicable && res.rows && res.rows.length) rows = res.rows;
        } catch (e) { }
      }
      if (!rows && topN) rows = c._rawOriginalData.slice();
      if (!rows) return;
      if (topN) rows = rows.slice(0, topN);
      D.updateVisual(id, { data: rows }); n++;
    }));
    if (fs && D.renderGlobalFilterPill) D.renderGlobalFilterPill({ filterValues: fs.values.map(v => fs.col + ' = ' + v) });
    if (root.Agent && root.Agent._appendMessage)
      root.Agent._appendMessage('agent', `🔍 Filtre appliqué à ${n} visuel(s) automatique(s)${fs ? ` : ${fs.col} = ${fs.values.join(', ')}` : ''}.`);
  }

  function clearGlobalFilter() {
    const D = root.Dashboard; if (!D) return;
    Visuals.items.forEach(it => {
      if (!it.spec || !it.spec.extraFilters || !it.spec.extraFilters.length) return;
      it.spec.extraFilters = [];
      try { pushSpec(D, it); } catch (e) { }
    });
    const reg = D.getRegistry ? D.getRegistry() : {};
    Object.keys(reg).forEach(id => { if (reg[id].config) reg[id].config._gf = []; });
    if (D.applyGlobalFilter) D.applyGlobalFilter({ clear: true });
  }

  function execute(intent) {
    const D = root.Dashboard;
    const notes = intent.notes ? intent.notes.slice() : [];
    const out = (reply, extra) => Object.assign({ reply: reply + (notes.length ? '\n\nℹ️ ' + notes.join('\nℹ️ ') : ''), created: [], suggestions: [] }, extra || {});
    if (!D) throw new Error("L'objet Dashboard n'est pas initialisé sur window.");

    if (intent.action === 'dashboard_bg') {
      const bg = intent.dashboardBg || '#0a0e17';
      if (D.setDashboardBackground) {
        D.setDashboardBackground(bg, true);
      }
      Memory.state.lastAction = 'dashboard_bg';
      Memory.save();
      return out(`🎨 Arrière-plan de tout le tableau de bord mis à jour : \`${bg}\`.\n\nLa couleur a été appliquée à l'ensemble du dashboard et enregistrée dans le catalogue pour persister après rechargement.`);
    }

    if (intent.action === 'global_filter') {
      const replies = [], f = Object.assign({}, intent.format || {});
      const { meta, style } = formatToMeta(f);
      if (Object.keys(meta).length || Object.keys(style).length) {
        const n = applyGlobalFormat(D, f);
        replies.push(`✨ **Appliqué à ${n} visuel(s)** : ${describeFormat(f) || 'mise en forme'}.`);
      }
      if (intent.clearFilter) { clearGlobalFilter(); replies.push('🔍 Filtres globaux supprimés, données restaurées.'); }
      else if (intent.globalDataFilter || intent.topN) replies.push(applyGlobalDataFilter(D, intent).message);
      if (!replies.length) replies.push("Je n'ai rien trouvé à appliquer. Ex : « bordure 4px bleue sur tous les visuels » ou « filtre tous les visuels sur statut = Actif ».");
      return out(replies.join('\n\n'));
    }

    if (intent.action === 'chat') return out(intent.chatReply || "Je t'écoute 🙂", { suggestions: ['Quels KPI sont disponibles ?'] });

    if (intent.action === 'list') {
      const cat = ensureCatalog(), lines = [];
      cat.summary.forEach(s => lines.push(`- **${s.label}** (indicateur global)`));
      cat.datasets.forEach(d => lines.push(`- **${d.measures.map(m => m.label).join(', ')}** par ${d.dimLabel}`));
      return out("📊 **KPIs & Dimensions disponibles :**\n" + lines.join('\n') + "\n\n💡 Exemple : *« Top 5 secteurs par CA en barres vertes »*.");
    }

    if (intent.action === 'undo') {
      const log = Memory.state.log;
      const last = log.pop();
      if (last && last.type === 'update') {
        const it = Visuals.bySid(last.sid);
        if (it) {
          const id = recreate(D, it, last.prev.cfg, last.prev.style);
          Visuals.update(last.sid, { id, spec: last.prev.spec, cfg: last.prev.cfg, style: last.prev.style });
          return out('↩️ Dernière modification annulée.');
        }
      }
      let sid = last && last.type === 'create' ? last.sid : (Visuals.count() ? Visuals.items[Visuals.count() - 1].sid : null);
      if (!sid) return out("Il n'y a rien à annuler.");
      const it = Visuals.bySid(sid);
      if (it) { try { D.removeVisual(it.id); } catch (e) { } Visuals.remove(sid); }
      Memory.state.activeSid = Visuals.count() ? Visuals.items[Visuals.count() - 1].sid : null;
      return out('↩️ Dernier visuel annulé.');
    }

    if (intent.action === 'explain') {
      const it = activeItem(intent); const reg = it && D.getRegistry ? D.getRegistry()[it.id] : null;
      const c = (it && it.cfg) || (reg && reg.config);
      if (!c) return out("Je n'ai pas de visuel à expliquer.");
      return out(`🔎 **${c.title}**\nType : ${c.chartType} · ${c.subtitle || ''}\nMesure : ${c.metricLabel || 'n/a'}` + (c.data ? ` · ${c.data.length} points` : '') +
        `\n\n\`\`\`sql\n${c.sql || ''}\n\`\`\`\n\`\`\`\n${c.dax || ''}\n\`\`\`` + (c.superset ? `\n**Superset :**\n\`\`\`json\n${JSON.stringify(c.superset, null, 2)}\n\`\`\`` : ''));
    }

    if (intent.action === 'delete') {
      const it = activeItem(intent); if (!it) return out("⚠️ Aucun visuel actif à supprimer.");
      const title = (D.list ? (D.list().find(v => v.id === it.id) || {}).title : '') || (it.cfg && it.cfg.title) || it.id;
      D.removeVisual(it.id); if (it.sid) Visuals.remove(it.sid);
      if (it.sid) deleteVisualFromBackend(it.sid);
      Memory.state.activeSid = Visuals.count() ? Visuals.items[Visuals.count() - 1].sid : null;
      return out(`🗑️ Visuel supprimé : « ${title} ».`);
    }

    if (intent.action === 'show') {
      const id = activeVisualId(intent); if (!id) return out("⚠️ Aucun visuel n'est affiché.");
      const card = (typeof document !== 'undefined') ? document.getElementById(id) : null;
      if (card && card.scrollIntoView) { card.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
      return out(`🎯 Visuel mis en évidence.`);
    }

    if (intent.action === 'update') {
      const item = activeItem(intent);
      if (!item) throw new NoActiveVisual('Aucun visuel actif à modifier.');
      if (item.legacy || !item.spec) return legacyUpdate(item.id, intent, out, notes, D);
      const prev = clone({ spec: item.spec, cfg: item.cfg, style: item.style });
      const spec = item.spec;
      let done, built;
      try {
        done = applyIntentToSpec(spec, intent, notes);
        built = buildFromSpec(spec, notes);
      } catch (e) { item.spec = prev.spec; throw e; }
      const cfg = built.cfg, style = built.style;
      let id = item.id;
      const oldCfg = item.cfg || {};

      const mustRecreate =
        cfg.chartType !== oldCfg.chartType ||
        dataSignature(cfg) !== dataSignature(oldCfg) ||
        cfg.chartType === 'card' || oldCfg.chartType === 'card';

      if (mustRecreate) {
        id = recreate(D, item, cfg, style);
        notes.push('Visuel recréé pour appliquer les nouvelles données/type.');
      } else {
        D.updateVisual(id, cfg, style);
      }
      Visuals.update(spec.sid, { id, spec, cfg, style });
      Memory.state.log.push({ type: 'update', sid: spec.sid, prev });
      syncVisualToBackend({ sid: spec.sid, spec, cfg, style });
      return out('🎨 Visuel mis à jour : ' + (done.length ? done.join(' · ') : 'données rafraîchies') + '.' + sqlBlock([cfg.sql]),
        { chartType: cfg.chartType, sid: spec.sid, sql: cfg.sql, superset: cfg.superset, updatedId: id, suggestions: suggestFor(cfg.chartType, built.group) });
    }

    if (intent.action === 'create' && !intent.groups.length) {
      const cat = ensureCatalog();
      const P = normWords(intent.text || '');
      let matchedDs = cat.datasets.find(d => d.dimTerms.some(t => has(P, t)));
      if (!matchedDs && cat.datasets.length) matchedDs = cat.datasets[0];
      if (matchedDs) {
        intent.groups = [{ kind: 'dataset', ds: matchedDs, measures: [matchedDs.measures[0]], score: 4 }];
        intent.confident = true;
        notes.push(`Indicateur déduit automatiquement : ${matchedDs.measures[0].label} par ${matchedDs.dimLabel}`);
      } else {
        return askWhichKpi(intent);
      }
    }

    if (intent.action === 'create') {
      const created = [], titles = [], sqls = []; let lastType = null, lastSid = null, lastSuperset = null;
      intent.groups.forEach(g => {
        const spec = newSpec(g);
        applyIntentToSpec(spec, intent, notes);
        const built = buildFromSpec(spec, notes);
        const id = D.addVisual(built.cfg);
        if (!id) throw new Error('Le Dashboard a refusé de créer le visuel.');
        if (Object.keys(built.style).length && D.updateVisual) D.updateVisual(id, {}, built.style);
        Visuals.add({ sid: spec.sid, id, spec, cfg: built.cfg, style: built.style });
        Memory.state.log.push({ type: 'create', sid: spec.sid });
        syncVisualToBackend({ sid: spec.sid, spec, cfg: built.cfg, style: built.style });
        created.push(id);

        if (intent.comparison && built.cfg.data && built.cfg.data.length === 2) {
          const [a, b] = built.cfg.data;
          const labA = String(a[built.cfg.labelField]);
          const labB = String(b[built.cfg.labelField]);
          titles.push(`« ${built.cfg.title} » (${built.cfg.chartType}) — ${labA} : ${a[built.cfg.valueField]} · ${labB} : ${b[built.cfg.valueField]}`);
        } else {
          titles.push(`« ${built.cfg.title} » (${built.cfg.chartType})`);
        }
        sqls.push(built.cfg.sql);
        lastType = built.cfg.chartType; lastSid = spec.sid; lastSuperset = built.cfg.superset;
      });
      const f = describeFormat(intent.format);
      return out('✅ ' + (titles.length > 1 ? titles.length + ' visuels créés : ' : 'Visuel créé : ') + titles.join(' · ') + (f ? ' · ' + f : '') + '.' + sqlBlock(sqls),
        { created, chartType: lastType, sid: lastSid, sql: sqls.join('\n\n'), superset: lastSuperset, suggestions: suggestFor(lastType, intent.groups[0]) });
    }
    return askWhichKpi(intent);
  }

  /* ═══════════════════════ ERREURS VISUELLES ═══════════════════════ */
  const VisualErrorHandler = (function () {
    const ERROR_CODES = {
      NO_ACTIVE_VISUAL_TO_MODIFY: { code: 'ERR_VIS_003', title: 'Aucun Visuel Actif à Modifier', color: '#8b5cf6' },
      DATASET_EMPTY: { code: 'ERR_VIS_002', title: 'Données Non Disponibles ou Vides', color: '#ef4444' },
      RENDER_EXCEPTION: { code: 'ERR_VIS_005', title: "Erreur d'Exécution de Rendu", color: '#ec4899' }
    };
    function repairVisual(errType, intent) {
      const r = Object.assign({}, intent, { notes: (intent.notes || []).slice(), format: Object.assign({}, intent.format) });
      if (errType === 'NO_ACTIVE_VISUAL_TO_MODIFY') {
        if (!r.groups.length && activeMeasureIds().length) r.groups = groupsFromIds(activeMeasureIds());
        if (!r.groups.length) return null;
        r.action = 'create'; r.notes.push("Aucun visuel sélectionné : création d'un nouveau.");
        return r;
      }
      if (errType === 'RENDER_EXCEPTION' && r.chartType && r.chartType !== 'bar' && !r.chartExplicit) {
        r.chartType = 'bar'; r.notes.push('Rendu échoué : repli sur barres.'); return r;
      }
      return null;
    }
    function renderErrorVisualCard(errType, details, prompt) {
      const D = root.Dashboard; if (!CFG.errorVisualEnabled || !D || !D.addVisual) return null;
      const meta = ERROR_CODES[errType] || ERROR_CODES.RENDER_EXCEPTION;
      const id = D.addVisual({
        title: `⚠️ [${meta.code}] ${meta.title}`, subtitle: `Auto-Diagnostic · ${new Date().toLocaleTimeString('fr-FR')}`, chartType: 'card', domain: 'DIAGNOSTIC',
        cardValue: null, cardValueFormatted: meta.code, metricLabel: details ? String(details).slice(0, 90) : meta.title, cardBenchmark: `Requête : "${(prompt || '').slice(0, 60)}"`, _isDiagnosticCard: true
      });
      if (id && D.updateVisual) D.updateVisual(id, {}, { borderLeft: `4px solid ${meta.color}`, boxShadow: `0 0 20px ${meta.color}40` });
      return id;
    }
    return { ERROR_CODES, repairVisual, renderErrorVisualCard };
  })();
  function detectErrorType(err) {
    if (err instanceof NoActiveVisual) return 'NO_ACTIVE_VISUAL_TO_MODIFY';
    const m = String((err && err.message) || err || '').toLowerCase();
    if (m.includes('vide') || m.includes('aucune donn')) return 'DATASET_EMPTY';
    return 'RENDER_EXCEPTION';
  }

  /* ═══════════════════════ PROMPT CHAINING ═══════════════════════ */
  const PromptChain = (function () {
    async function step1(ctx) {
      const t0 = Date.now();
      const T0 = ascii(normalizeTypos(ctx.prompt));
      const target = GLOBAL_SCOPE_RE.test(T0) ? null : findVisualByTitleOrPrompt(ctx.prompt);
      const effective = target ? stripVisualRef(ctx.prompt, target) : ctx.prompt;
      let intent = ruleParse(effective);
      intent = resolveWithContext(effective, intent, target);
      intent.text = ctx.prompt;
      const boost = LocalLoRA.computeLoRABoost(ctx.prompt, intent);
      if (boost >= 0.55) { intent.confident = true; intent.notes.push(`Pattern appris (+${Math.round(boost * 100)}%)`); }
      ctx.intent = intent;
      ctx.chain.push({ step: 1, name: 'IntentAnalysis', ms: Date.now() - t0, action: intent.action, comparison: !!intent.comparison, baseline: intent.comparison ? intent.comparison.baseline : null });
    }
    async function step2(ctx) {
      const t0 = Date.now();
      const short = ctx.prompt.split(/\s+/).length <= 4;
      const r = await cragRetrieve(ctx.prompt, (ctx.intent.inherited || short) ? Memory.lastUserText() : '');
      ctx.crag = r; ctx.ragChunks = r.kept; ctx.ragContext = RAGStore.format(r.kept);
      ctx.chain.push({ step: 2, name: 'CorrectiveRAG', ms: Date.now() - t0, verdict: r.verdict, chunks: r.kept.length });
    }
    async function step3(ctx) {
      const t0 = Date.now(), i = ctx.intent;
      const needsKpi = (i.action === 'create' || i.action === 'unknown') && !i.groups.length;
      const lowConf = i.groups.length && (i.bestScore < 3.5 || i.ambiguous) && !i.inherited && i.action === 'create';
      const worthAgent = needsKpi ? (i.action === 'create' || (ctx.crag && ctx.crag.verdict !== 'incorrect')) : lowConf;
      if (worthAgent && ctx.crag) {
        const r = await AgenticRAG.resolve(ctx.prompt, ctx.crag);
        ctx.chain.push({ step: 3, name: 'AgenticRAG', ms: Date.now() - t0, source: r.source, confident: r.confident, ids: r.ids });
        if (r.confident && r.ids.length) {
          const gs = groupsFromIds(r.ids);
          if (gs.length) {
            i.groups = gs; i.notes.push(`RAG agentique (${r.source}).`);
            if (i.action === 'unknown') i.action = 'create';
            i.confident = true;
          }
        } else if (needsKpi && r.candidates.length && i.action === 'create') ctx.clarify = r.candidates;
      }
      const needLLM = CFG.useLLM && !ctx.clarify && !PROTECTED_ACTIONS.includes(i.action) && (
        CFG.alwaysLLM || (!i.confident && !i.groups.length) ||
        (i.action === 'create' && !i.groups.length) || i.action === 'unknown'
      );
      if (needLLM) {
        const t1 = Date.now();
        try { const r = await callLLMWithRAG(ctx.prompt, ctx.ragContext); ctx.intent = mergeLLM(ctx.intent, r); ctx.chain.push({ step: '3b', name: 'LLMPlanning', ms: Date.now() - t1, action: r.action }); }
        catch (e) { ctx.chain.push({ step: '3b', name: 'LLMPlanning', ms: Date.now() - t1, failed: e.message }); }
      }
      const confidence = computeIntentConfidence(ctx.intent);
      const needsGemini = CFG.geminiEnabled && CFG.geminiApiKey && !PROTECTED_ACTIONS.includes(ctx.intent.action) &&
        (confidence < CFG.geminiConfidenceThreshold || ctx.intent.action === 'unknown' || !!ctx.clarify) &&
        !ctx.intent.comparison;
      if (needsGemini) {
        const t2 = Date.now();
        const geminiIntent = await callGeminiFallback(ctx.prompt, ctx.ragContext);
        if (geminiIntent) {
          ctx.intent = mergeGemini(ctx.intent, geminiIntent);
          ctx.clarify = null;
          ctx.intent.confident = true;
          ctx.chain.push({ step: '3c', name: 'GeminiFallback', ms: Date.now() - t2, action: geminiIntent.action });
        } else {
          ctx.chain.push({ step: '3c', name: 'GeminiFallback', ms: Date.now() - t2, failed: true });
        }
      }
      const vt = []; verifyIntent(ctx.intent, vt); if (vt.length) ctx.chain.push({ step: '3d', name: 'Verify', fixes: vt });
    }
    async function step4(ctx) {
      const t0 = Date.now(); let result = null, err = null, ok = true;
      if (ctx.clarify) { result = askWhichKpi(ctx.intent, ctx.clarify); }
      if (!result && ctx.intent.action === 'unknown' && !ctx.intent.groups.length) {
        let txt = null;
        if (CFG.useLLM) { try { txt = await callLLMChat(ctx.prompt); } catch (e) { } }
        if (txt) result = { reply: txt, created: [], suggestions: ['Quels KPI sont disponibles ?'] };
        else ctx.intent.action = 'create';
      }
      if (!result) {
        try { result = execute(ctx.intent); } catch (e) { err = e; }
        if (err) {
          const type = detectErrorType(err);
          ctx.chain.push({ step: '4a', name: 'ErrorDetected', type, error: err.message });
          const fixed = CFG.autoModifyVisualOnError ? VisualErrorHandler.repairVisual(type, ctx.intent) : null;
          if (fixed) {
            try { result = execute(fixed); ctx.intent = fixed; err = null; ctx.chain.push({ step: '4b', name: 'SelfCorrection', ok: true }); }
            catch (e2) { err = e2; }
          } else if (type === 'NO_ACTIVE_VISUAL_TO_MODIFY') { result = askWhichKpi(ctx.intent); err = null; }
          if (err) {
            ok = false;
            VisualErrorHandler.renderErrorVisualCard(detectErrorType(err), err.message, ctx.prompt);
            result = { reply: `⚠️ Je n'ai pas pu afficher : ${err.message}. Carte de diagnostic ajoutée.`, created: [], suggestions: ['Quels KPI sont disponibles ?'] };
          }
        }
      }
      if (ok && !result.needsInput) { LocalLoRA.record(ctx.prompt, ctx.intent, true); Memory.commit(ctx.intent, result); }
      ctx.result = result;
      ctx.chain.push({ step: 4, name: 'Execution', ms: Date.now() - t0, ok, created: (result.created || []).length });
    }
    async function plan(ctx) { await step1(ctx); if (CFG.enableChaining) { await step2(ctx); await step3(ctx); } }
    async function run(ctx) {
      let timer;
      const guard = new Promise((_, rej) => { timer = setTimeout(() => rej(new Error('Délai de la chaîne dépassé')), CFG.chainTimeout); });
      try { await Promise.race([(async () => { await plan(ctx); await step4(ctx); })(), guard]); }
      finally { clearTimeout(timer); }
    }
    return { run, plan };
  })();

  /* ═══════════════════════ RESTAURATION ═══════════════════════ */
  let _restoreP = null, _restoreDone = false, _firstRestore = true;
  let _restoreInfo = { visuals: 0, turns: 0, failures: 0, pending: 0 };

  function waitDashboard(ms) {
    return new Promise(resolve => {
      const t0 = Date.now();
      (function poll() {
        const D = root.Dashboard;
        const grid = (typeof document !== 'undefined') && document.getElementById('visuals-grid');
        const ready = D && typeof D.addVisual === 'function' && grid && grid.isConnected;
        if (ready) return resolve(D);
        if (Date.now() - t0 >= ms) return resolve(null);
        setTimeout(poll, 100);
      })();
    });
  }

  async function restore() {
    Memory.load();
    _restoreInfo.turns = Memory.turns.length;
    if (!CFG.persist) return _restoreInfo;

    // ── Fusionner localStorage + backend ──
    let saved = Store.get(CFG.storageKeyVisuals) || [];
    let backendVisuals = [];
    if (ORIGIN) {
      try {
        const resp = await fetch(ORIGIN + '/api/agent/visuals/prompt', { method: 'GET' });
        if (resp.ok) {
          const data = await resp.json();
          backendVisuals = (data.visuals || []).filter(v => v && v.sid);
        }
      } catch (e) {
        console.warn('[BIAgent.restore] Backend fetch failed, checking static kpis_catalog.json:', e);
      }
    }
    if (!backendVisuals.length && typeof fetch === 'function') {
      try {
        const catResp = await fetch((CFG.catalogUrl || 'kpis_catalog.json') + '?_t=' + Date.now());
        if (catResp.ok) {
          const catData = await catResp.json();
          backendVisuals = (catData.prompt_visuals || []).filter(v => v && v.sid);
        }
      } catch (e) { }
    }

    if (backendVisuals.length > 0) {
      const localSids = new Set(saved.map(s => s.sid));
      const backendSids = new Set(backendVisuals.map(v => v.sid));
      backendVisuals.forEach(bv => {
        if (!localSids.has(bv.sid)) saved.push(bv);
        else {
          const idx = saved.findIndex(s => s.sid === bv.sid);
          if (idx >= 0) saved[idx] = bv;
        }
      });
      saved = saved.filter(s => !s.spec || backendSids.has(s.sid));
    }

    if (!saved.length) { _restoreDone = true; return _restoreInfo; }

    const D = await waitDashboard(CFG.restoreWaitMs);
    if (!D) { console.warn('[BIAgent.restore] Dashboard indisponible, storage conservé'); _restoreInfo.pending = saved.length; return _restoreInfo; }

    if (_firstRestore) {
      _firstRestore = false;
    }

    const reg = D.getRegistry ? D.getRegistry() : null;
    const items = []; let failures = 0;
    saved.forEach(s => {
      let id = null;
      if (reg) Object.keys(reg).forEach(k => {
        if (reg[k] && reg[k].config && reg[k].config._agentSid === s.sid) id = k;
      });
      if (!id) {
        if (s.spec && (!s.cfg || !s.cfg.data || !s.cfg.data.length)) {
          try {
            const built = buildFromSpec(s.spec, []);
            s.cfg = built.cfg;
            if (!s.style || !Object.keys(s.style).length) s.style = built.style;
          } catch (e) { }
        }
        try {
          id = D.addVisual(Object.assign({}, s.cfg, { _agentSid: s.sid }));
          if (id && s.style && Object.keys(s.style).length && D.updateVisual) D.updateVisual(id, {}, s.style);
        } catch (e) { console.warn('[BIAgent.restore] échec', s.sid, e); id = null; }
      }
      if (id) items.push({ sid: s.sid, id, spec: s.spec, cfg: s.cfg, style: s.style || {} });
      else failures++;
    });
    Visuals.setAll(items);
    if (failures === 0) Visuals.persist();
    else console.warn('[BIAgent.restore] ' + failures + ' visuel(s) non restauré(s), storage conservé');
    _restoreInfo.visuals = items.length; _restoreInfo.failures = failures;
    _restoreDone = true;
    return _restoreInfo;
  }
  const restoreOnce = () => (_restoreP || (_restoreP = restore().then(r => { _restoreDone = true; return r; }).catch(e => { console.warn('[BIAgent.restore] failed', e); _restoreDone = true; return _restoreInfo; })));

  /* ═══════════════════════ POINT D'ENTRÉE ═══════════════════════ */
  async function handle(text) {
    ensureCatalog();
    await restoreOnce();
    const prompt = String(text || '').trim();
    const started = Date.now();
    Memory.addTurn('user', prompt);
    const finish = (res, extra) => {
      const reply = res.reply || 'Fait.';
      Memory.addTurn('assistant', reply, { created: res.created });
      return Object.assign({ reply, created: res.created || [], suggestions: res.suggestions || [], needsInput: !!res.needsInput, sql: res.sql || null, superset: res.superset || null, totalTimeMs: Date.now() - started }, extra || {});
    };
    if (!prompt) return finish({ reply: 'Dis-moi ce que tu veux voir 🙂' });

    const pend = resolvePending(prompt);
    if (pend) {
      Memory.clearPending();
      if (pend.cancel) return finish({ reply: "D'accord, j'annule.", suggestions: ['Quels KPI sont disponibles ?'] });
      if (pend.choice) {
        const base = pend.p.intent;
        const intent = Object.assign({}, base, { groups: groupsFromIds([pend.choice.id]), notes: [`Choix : ${pend.choice.label}`], action: base.action === 'unknown' || base.action === 'update' ? 'create' : base.action, confident: true });
        const ctx = { prompt, intent, chain: [], result: null };
        try { ctx.result = execute(intent); Memory.commit(intent, ctx.result); LocalLoRA.record(base.text, intent, true); }
        catch (e) { ctx.result = { reply: '⚠️ ' + e.message, created: [] }; }
        return finish(ctx.result, { intent, chain: ctx.chain });
      }
    } else if (Memory.state.pending) Memory.clearPending();

    const ctx = { prompt, chainId: uid('chain_'), chain: [], intent: null, ragChunks: [], ragContext: '', result: null, crag: null, clarify: null };
    try { await PromptChain.run(ctx); }
    catch (e) { ctx.result = ctx.result || { reply: '⚠️ ' + e.message, created: [] }; }
    return finish(ctx.result || { reply: 'Traitement terminé.' }, { intent: ctx.intent, chainId: ctx.chainId, chain: ctx.chain });
  }

  async function promptToSQL(text) {
    ensureCatalog(); await restoreOnce();
    const ctx = { prompt: String(text || ''), chain: [], intent: null, crag: null, clarify: null, ragChunks: [], ragContext: '' };
    await PromptChain.plan(ctx);
    const intent = ctx.intent, notes = intent.notes.slice();
    let spec;
    const act = activeSpec();
    if (intent.action === 'update' && act) spec = clone(act); else if (intent.groups.length) spec = newSpec(intent.groups[0]); else return { sql: null, notes: ['KPI non identifié'], chain: ctx.chain };
    applyIntentToSpec(spec, intent, notes);
    const built = buildFromSpec(spec, notes);
    return { sql: built.cfg.sql, superset: built.cfg.superset, chartType: built.cfg.chartType, spec, notes, chain: ctx.chain };
  }

  async function init(opts) {
    Object.assign(CFG, opts || {});
    if (!CFG.geminiApiKey && Store.ok()) {
      try { const k = localStorage.getItem('bi_agent_gemini_key'); if (k) CFG.geminiApiKey = k.trim(); } catch (e) { }
    }
    CATALOG = buildCatalog(root.BI_DATA_STORE); _vocab = null;
    let merged = 0;
    if (CFG.catalogUrl && typeof fetch === 'function') { try { const r = await fetch(CFG.catalogUrl); if (r.ok) merged = mergeExternalCatalog(CATALOG, await r.json()); } catch (e) { } }
    RAGStore.build(root.BI_DATA_STORE, CATALOG);
    if (CFG.loraEnabled) LocalLoRA.scanFolderDataFiles().catch(() => { });
    const rest = await restoreOnce();
    if (typeof CFG.onRestore === 'function') { try { CFG.onRestore(Memory.turns.slice(), Visuals.items.map(v => ({ sid: v.sid, id: v.id, title: v.cfg && v.cfg.title }))); } catch (e) { } }
    return {
      datasets: CATALOG.datasets.length, summaryKpis: CATALOG.summary.length, externalMerged: merged,
      ragChunksIndexed: RAGStore.chunks.length, loraFiles: LocalLoRA.dataFiles.length,
      restoredVisuals: rest.visuals, restoredTurns: rest.turns, restoreFailures: rest.failures || 0,
      geminiEnabled: !!CFG.geminiApiKey
    };
  }

  const lora = (hp, cb) => LocalLoRA.finetune(hp, cb);
  const api = {
    CFG, init, handle, promptToSQL, lora, trainLoRA: lora,
    reset: () => Memory.reset(),
    clearVisuals: () => { const D = root.Dashboard; Visuals.items.forEach(v => { try { D && D.removeVisual(v.id); } catch (e) { } }); Visuals.clear(); Memory.state.activeSid = null; Memory.save(); },
    getTranscript: () => Memory.turns.slice(),
    getVisuals: () => Visuals.items.map(v => ({ sid: v.sid, id: v.id, spec: v.spec, sql: v.cfg && v.cfg.sql, superset: v.cfg && v.cfg.superset })),
    getMemory: () => Memory,
    ragSearch: (q, k) => { ensureCatalog(); return RAGStore.search(q, k || CFG.maxChunks); },
    scanFolderDataFiles: () => LocalLoRA.scanFolderDataFiles(),
    getCatalog: () => ensureCatalog(), getRAGStore: () => RAGStore, getLoRA: () => LocalLoRA, getVisualErrorHandler: () => VisualErrorHandler,
    setGeminiKey: (key) => {
      CFG.geminiApiKey = key; CFG.geminiEnabled = !!key;
      try { if (Store.ok()) localStorage.setItem('bi_agent_gemini_key', key || ''); } catch (e) { }
      return { geminiEnabled: !!key };
    },
    deleteVisual: deleteVisual,
    clearGlobalFilter,
    syncVisualFromDashboard: syncVisualFromDashboard,
    _ruleParse: ruleParse, _buildCatalog: buildCatalog, _mergeLLM: mergeLLM, _mergeGemini: mergeGemini,
    _mergeExternalCatalog: mergeExternalCatalog, _resetCatalog: () => { CATALOG = null; _vocab = null; },
    _detectComparisonSplit: detectComparisonSplit, _extractBaseline: extractBaseline,
    _normalizeTypos: normalizeTypos
  };
  root.BIAgent = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})();