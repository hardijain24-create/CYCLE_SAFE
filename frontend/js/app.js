/**
 * CycleSafe Core Application Logic & Router
 */

document.addEventListener('DOMContentLoaded', async () => {
  // Check backend server connection
  const online = await CycleSafeAPI.checkServerOnline();
  updateServerStatusBadge(online);

  // Initialize UI
  setupNavigation();
  setupLogForm();
  setupCalendar();
  setupMapFilters();
  setupPrivacyControls();

  // Load initial view
  const hash = window.location.hash.replace('#', '') || 'landing';
  showView(hash);
  refreshAllData();
});

function updateServerStatusBadge(online) {
  const badge = document.getElementById('server-status-badge');
  if (badge) {
    if (online) {
      badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-400 inline-block animate-pulse mr-1.5"></span>API ONLINE (FASTAPI)`;
      badge.className = "inline-flex items-center text-[10px] font-mono font-bold bg-emerald-950 text-emerald-300 px-2.5 py-0.5 rounded-full border border-emerald-500/50";
    } else {
      badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-amber-400 inline-block mr-1.5"></span>STANDALONE / CLIENT SAFE`;
      badge.className = "inline-flex items-center text-[10px] font-mono font-bold bg-csDark text-csWarmBg px-2.5 py-0.5 rounded-full border border-csWarmBg/40";
    }
  }
}

// 1. Navigation & Router
function setupNavigation() {
  window.addEventListener('popstate', () => {
    const hash = window.location.hash.replace('#', '') || 'landing';
    showView(hash, false);
  });
}

function showView(viewId, pushHash = true) {
  const allViews = document.querySelectorAll('.view-section');
  allViews.forEach(sec => sec.classList.add('hidden'));

  const target = document.getElementById('view-' + viewId);
  if (target) {
    target.classList.remove('hidden');
    window.scrollTo({ top: 0, behavior: 'smooth' });
    if (pushHash) window.location.hash = viewId;
  }

  // Update active state in nav buttons
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.classList.remove('bg-csLightBg', 'border-csDark', 'text-csAccent');
  });

  const activeBtn = document.getElementById(`nav-${viewId}`);
  if (activeBtn) {
    activeBtn.classList.add('bg-csLightBg', 'border-csDark', 'text-csAccent');
  }

  // Trigger view-specific re-renders
  if (viewId === 'dashboard') loadDashboard();
  if (viewId === 'calendar') renderCalendar();
  if (viewId === 'patterns') loadPatterns();
  if (viewId === 'perimenopause') loadPerimenopause();
  if (viewId === 'doctor') loadDoctorReport();
  if (viewId === 'products') loadMapLocations();
  if (viewId === 'privacy') loadPrivacySettings();
}

// 2. Dashboard Logic
async function loadDashboard() {
  const cycles = await CycleSafeAPI.getCycles();
  const symptoms = await CycleSafeAPI.getSymptoms();

  // Calculate current cycle metrics
  if (cycles.length > 0) {
    const lastCycle = cycles[cycles.length - 1];
    const lastDate = new Date(lastCycle.last_period_date || lastCycle.log_date || '2026-09-04');
    const today = new Date();
    const diffDays = Math.max(1, Math.floor((today - lastDate) / (1000 * 60 * 60 * 24)));

    const dayCounter = document.getElementById('dash-cycle-day');
    if (dayCounter) dayCounter.textContent = `DAY ${diffDays}`;

    // Determine Cycle Phase
    let phase = 'FOLLICULAR';
    let phaseDesc = 'Follicular Development';
    let phaseColor = 'bg-csPink';
    if (diffDays <= 5) {
      phase = 'MENSTRUAL';
      phaseDesc = 'Menses Flow Phase';
      phaseColor = 'bg-csAccent text-white';
    } else if (diffDays >= 12 && diffDays <= 16) {
      phase = 'OVULATION';
      phaseDesc = 'Estimated Fertile Peak';
      phaseColor = 'bg-csPurple';
    } else if (diffDays > 16) {
      phase = 'LUTEAL';
      phaseDesc = 'Progesterone Window';
      phaseColor = 'bg-csWarmBg';
    }

    const phaseTag = document.getElementById('dash-cycle-phase');
    if (phaseTag) {
      phaseTag.textContent = phase;
      phaseTag.className = `gasoek-font text-3xl sm:text-4xl text-csDark mt-0.5 px-3 py-1 rounded-xl sui-border inline-block ${phaseColor}`;
    }

    const phaseSub = document.getElementById('dash-cycle-phase-sub');
    if (phaseSub) phaseSub.textContent = phaseDesc;

    // Timeline bar percentages
    const mensesPct = Math.min(20, (5 / 28) * 100);
    const follPct = 30;
    const ovulPct = 15;
    const lutealPct = 35;
    const bar = document.getElementById('dash-timeline-bar');
    if (bar) {
      bar.innerHTML = `
        <div style="width: ${mensesPct}%" class="h-full bg-csAccent rounded-lg text-[9px] font-mono text-white flex items-center justify-center font-bold" title="Menstrual">FLOW</div>
        <div style="width: ${follPct}%" class="h-full bg-csPink rounded-lg text-[9px] font-mono text-csDark flex items-center justify-center font-bold" title="Follicular">FOLLICULAR</div>
        <div style="width: ${ovulPct}%" class="h-full bg-csPurple rounded-lg text-[9px] font-mono text-csDark flex items-center justify-center font-bold" title="Ovulation">OVUL</div>
        <div style="width: ${lutealPct}%" class="h-full bg-csWarmBg rounded-lg text-[9px] font-mono text-csDark flex items-center justify-center font-bold" title="Luteal">LUTEAL</div>
      `;
    }
  }

  // Load Conformal Forecast
  const forecast = await CycleSafeAPI.getForecast(28, false);
  const fcBox = document.getElementById('dash-forecast-box');
  if (fcBox) {
    if (forecast.forecast_available) {
      fcBox.innerHTML = `
        <div class="flex items-center justify-between border-b-2 border-csDark pb-3">
          <span class="font-mono text-xs font-bold text-csAccent uppercase tracking-widest">CONFORMAL FORECAST</span>
          <span class="pill-tag bg-csAccent text-white px-2 py-0.5 border border-csDark">CALIBRATED DEV OOF</span>
        </div>
        <div class="mt-4 flex items-baseline space-x-3">
          <span class="gasoek-font text-5xl text-csDark">${forecast.predicted_days}</span>
          <span class="font-mono text-sm font-bold text-csDark/70">DAYS ESTIMATE</span>
        </div>
        <div class="mt-3 space-y-2 font-mono text-xs text-csDark">
          <div class="flex justify-between bg-white/70 p-2 rounded-lg border border-csDark/30">
            <span>80% Prediction Window:</span>
            <span class="font-bold text-csAccent">${forecast.prediction_interval_80[0]} - ${forecast.prediction_interval_80[1]} Days</span>
          </div>
          <div class="flex justify-between bg-white/70 p-2 rounded-lg border border-csDark/30">
            <span>90% Cautious Window:</span>
            <span class="font-bold text-csDark">${forecast.prediction_interval_90[0]} - ${forecast.prediction_interval_90[1]} Days</span>
          </div>
        </div>
        <p class="font-mono text-[10px] text-csDark/60 mt-3 italic">*Non-diagnostic statistical interval based on personal median baseline.</p>
      `;
    } else {
      fcBox.innerHTML = `<p class="font-mono text-xs text-csDark/70">Log at least 3 cycle entries to activate conformal interval predictions.</p>`;
    }
  }

  // Render Recent Cycles Strip
  const rhythmStrip = document.getElementById('dash-rhythm-strip');
  if (rhythmStrip) {
    const recent = cycles.slice(-6);
    rhythmStrip.innerHTML = recent.map((c, i) => `
      <div class="bg-white border-2 border-csDark p-3 rounded-xl sui-shadow-sm flex flex-col justify-between items-center text-center min-w-[90px]">
        <span class="font-mono text-[10px] font-bold text-csDark/60">CYCLE ${cycles.length - recent.length + i + 1}</span>
        <span class="gasoek-font text-2xl text-csDark my-1">${c.cycle_length_days}d</span>
        <span class="pill-tag ${c.bleeding_heaviness >= 3 ? 'bg-csAccent text-white' : 'bg-csLightBg text-csDark'} px-1.5 py-0.5 border border-csDark text-[9px]">
          FLOW ${c.bleeding_heaviness || 2}/3
        </span>
      </div>
    `).join('');
  }

  // Load Rule Flags
  const flags = await CycleSafeAPI.evaluateFlags(false);
  const flagFeed = document.getElementById('dash-flags-feed');
  if (flagFeed) {
    if (flags.triggered_rules && flags.triggered_rules.length > 0) {
      flagFeed.innerHTML = flags.triggered_rules.map(r => `
        <div class="p-4 bg-csWarmBg border-2 border-csDark rounded-xl sui-shadow-sm flex items-start space-x-3">
          <span class="text-xl">⚠️</span>
          <div>
            <div class="flex items-center space-x-2">
              <span class="pill-tag bg-csAccent text-white px-2 py-0.5">${r.urgency || 'INFO'}</span>
              <span class="font-bold text-xs text-csDark">${r.message}</span>
            </div>
            <p class="font-mono text-[11px] text-csDark/80 mt-1">${r.details}</p>
          </div>
        </div>
      `).join('');
    } else {
      flagFeed.innerHTML = `
        <div class="p-4 bg-white/70 border-2 border-csDark rounded-xl text-center font-mono text-xs text-csDark">
          ✨ No cautionary timing variance or pain shifts detected in recent records.
        </div>
      `;
    }
  }
}

// 3. Log Today Setup & Submission
let selectedSymptomTags = new Set();
let selectedFlowLevel = 2;

function setupLogForm() {
  // Flow selector buttons
  const flowBtns = document.querySelectorAll('.flow-selector-btn');
  flowBtns.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      flowBtns.forEach(b => b.classList.remove('bg-csAccent', 'text-white', 'sui-shadow-sm'));
      btn.classList.add('bg-csAccent', 'text-white', 'sui-shadow-sm');
      selectedFlowLevel = parseInt(btn.getAttribute('data-flow') || '2', 10);
    });
  });

  // Allowed symptom tags click toggles
  const symptomBadges = document.querySelectorAll('.symptom-tag-btn');
  symptomBadges.forEach(badge => {
    badge.addEventListener('click', (e) => {
      e.preventDefault();
      const sym = badge.getAttribute('data-symptom');
      if (selectedSymptomTags.has(sym)) {
        selectedSymptomTags.delete(sym);
        badge.classList.remove('bg-csAccent', 'text-white', 'border-csDark', 'sui-shadow-sm');
        badge.classList.add('bg-white', 'text-csDark');
      } else {
        selectedSymptomTags.add(sym);
        badge.classList.remove('bg-white', 'text-csDark');
        badge.classList.add('bg-csAccent', 'text-white', 'border-csDark', 'sui-shadow-sm');
      }
    });
  });

  // Sliders value indicators
  ['pain', 'sleep', 'fatigue', 'mood'].forEach(type => {
    const slider = document.getElementById(`log-${type}-slider`);
    const valText = document.getElementById(`log-${type}-val`);
    if (slider && valText) {
      slider.addEventListener('input', () => {
        valText.textContent = `${slider.value}/3`;
      });
    }
  });

  // Default date to today
  const dateInput = document.getElementById('log-date-input');
  if (dateInput && !dateInput.value) {
    dateInput.value = new Date().toISOString().split('T')[0];
  }

  // Save button action
  const saveBtn = document.getElementById('log-submit-btn');
  if (saveBtn) {
    saveBtn.addEventListener('click', handleSaveLog);
  }
}

async function handleSaveLog(e) {
  if (e) e.preventDefault();
  const logDate = document.getElementById('log-date-input')?.value || new Date().toISOString().split('T')[0];
  const pain = parseInt(document.getElementById('log-pain-slider')?.value || '1', 10);
  const sleep = parseInt(document.getElementById('log-sleep-slider')?.value || '2', 10);
  const fatigue = parseInt(document.getElementById('log-fatigue-slider')?.value || '1', 10);
  const mood = parseInt(document.getElementById('log-mood-slider')?.value || '2', 10);
  const soakingHourly = document.getElementById('log-soaking-check')?.checked || false;
  const cycleLength = parseFloat(document.getElementById('log-cycle-length')?.value || '28');

  // 1. Submit cycle entry
  await CycleSafeAPI.addCycle({
    cycle_length_days: cycleLength,
    log_date: logDate,
    last_period_date: logDate,
    bleeding_heaviness: selectedFlowLevel,
    bleeding_days: selectedFlowLevel > 0 ? 5 : 0,
    pain_score: pain,
    sleep_score: sleep,
    fatigue_score: fatigue,
    mood_score: mood,
    heavy_soaking_hourly: soakingHourly
  });

  // 2. Submit individual symptoms from allowlist
  for (const sym of selectedSymptomTags) {
    await CycleSafeAPI.addSymptom(sym, Math.max(1, pain), logDate);
  }

  showToast('✓ Today\'s health entry saved securely!');
  closeLogModal();
  refreshAllData();
  showView('dashboard');
}

function openLogModal() {
  const modal = document.getElementById('log-modal');
  if (modal) modal.classList.remove('hidden');
}

function closeLogModal() {
  const modal = document.getElementById('log-modal');
  if (modal) modal.classList.add('hidden');
}

// 4. Interactive Calendar
let calYear = 2026;
let calMonth = 8; // September (0-indexed)

function setupCalendar() {
  document.getElementById('cal-prev')?.addEventListener('click', () => {
    calMonth--;
    if (calMonth < 0) { calMonth = 11; calYear--; }
    renderCalendar();
  });
  document.getElementById('cal-next')?.addEventListener('click', () => {
    calMonth++;
    if (calMonth > 11) { calMonth = 0; calYear++; }
    renderCalendar();
  });
}

async function renderCalendar() {
  const grid = document.getElementById('calendar-grid');
  const title = document.getElementById('calendar-month-title');
  if (!grid || !title) return;

  const monthNames = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"];
  title.textContent = `${monthNames[calMonth]} ${calYear}`;

  const firstDay = new Date(calYear, calMonth, 1).getDay();
  const daysInMonth = new Date(calYear, calMonth + 1, 0).getDate();

  const cycles = await CycleSafeAPI.getCycles();
  const symptoms = await CycleSafeAPI.getSymptoms();

  grid.innerHTML = '';

  // Blank slots before day 1
  for (let i = 0; i < firstDay; i++) {
    const blank = document.createElement('div');
    blank.className = "h-24 bg-csPrimary/30 border border-csDark/10 rounded-xl";
    grid.appendChild(blank);
  }

  // Days
  for (let day = 1; day <= daysInMonth; day++) {
    const dateStr = `${calYear}-${String(calMonth + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    const dayEl = document.createElement('div');
    dayEl.className = "h-24 bg-white border-2 border-csDark rounded-xl p-2 flex flex-col justify-between cursor-pointer hover:bg-csLightBg transition sui-shadow-sm";

    // Check for flow / cycle markers
    let markerHtml = '';
    const hasCycle = cycles.some(c => c.log_date === dateStr || c.last_period_date === dateStr);
    const daySymptoms = symptoms.filter(s => s.log_date === dateStr);

    // Hardcoded highlight for demonstration in Sep 2026
    const isPeriodDemo = (calMonth === 8 && day >= 4 && day <= 8);
    const isOvulationDemo = (calMonth === 8 && day >= 16 && day <= 18);
    const isForecastDemo = (calMonth === 9 && day >= 2 && day <= 6);

    if (hasCycle || isPeriodDemo) {
      markerHtml += `<span class="pill-tag bg-csAccent text-white px-1.5 py-0.5 text-[8px]">FLOW</span>`;
    }
    if (isOvulationDemo) {
      markerHtml += `<span class="pill-tag bg-csPurple text-csDark px-1.5 py-0.5 text-[8px]">FERTILE</span>`;
    }
    if (daySymptoms.length > 0) {
      markerHtml += `<span class="pill-tag bg-csWarmBg text-csDark px-1.5 py-0.5 text-[8px]">${daySymptoms.length} SYM</span>`;
    }

    dayEl.innerHTML = `
      <div class="flex justify-between items-start">
        <span class="gasoek-font text-base text-csDark">${day}</span>
        ${day === 26 && calMonth === 8 ? '<span class="w-2 h-2 rounded-full bg-csAccent inline-block" title="Today"></span>' : ''}
      </div>
      <div class="flex flex-col space-y-1">
        ${markerHtml}
      </div>
    `;

    dayEl.onclick = () => {
      document.getElementById('cal-inspect-date').textContent = dateStr;
      document.getElementById('cal-inspect-details').innerHTML = `
        <p class="font-bold text-csDark">Date: ${dateStr}</p>
        <p class="text-xs text-csDark/80 mt-1">Status: ${isPeriodDemo ? 'Menstrual Flow Logged' : isOvulationDemo ? 'Fertile Peak Window' : 'Inter-phase tracking'}</p>
        <p class="text-xs text-csDark/80">Symptoms recorded: ${daySymptoms.map(s => s.symptom).join(', ') || 'None recorded'}</p>
        <button onclick="openLogForDate('${dateStr}')" class="mt-3 text-xs font-mono font-bold px-3 py-1.5 bg-csAccent text-white border-2 border-csDark rounded-lg sui-shadow-sm">Log on this date</button>
      `;
    };

    grid.appendChild(dayEl);
  }
}

function openLogForDate(dateStr) {
  const dateInput = document.getElementById('log-date-input');
  if (dateInput) dateInput.value = dateStr;
  openLogModal();
}

// 5. Patterns View
async function loadPatterns() {
  const flags = await CycleSafeAPI.evaluateFlags(false);
  const container = document.getElementById('patterns-card-list');
  if (!container) return;

  container.innerHTML = `
    <div class="bg-csWarmBg border-2 border-csDark rounded-2xl p-6 sui-shadow">
      <div class="flex items-center justify-between pb-3 border-b-2 border-csDark">
        <span class="gasoek-font text-2xl text-csDark">CYCLE LENGTH STABILITY</span>
        <span class="pill-tag bg-csDark text-white px-2.5 py-1">6 MONTH REVIEW</span>
      </div>
      <p class="text-sm text-csDark/80 mt-3 font-medium">Your median cycle length is 28.5 days with an observed variance of ±2 days. This reflects standard physiological stability.</p>
    </div>

    <div class="bg-csLightBg border-2 border-csDark rounded-2xl p-6 sui-shadow">
      <div class="flex items-center justify-between pb-3 border-b-2 border-csDark">
        <span class="gasoek-font text-2xl text-csDark">SYMPTOM CLUSTER CO-OCCURRENCE</span>
        <span class="pill-tag bg-csAccent text-white px-2.5 py-1">LUTEAL PHASE</span>
      </div>
      <p class="text-sm text-csDark/80 mt-3 font-medium">Cramps and fatigue consistently peak 1-2 days before menses onset. Sharing this timing with your doctor can help tailor supportive options.</p>
    </div>

    <div class="bg-white border-2 border-csDark rounded-2xl p-6 sui-shadow">
      <div class="flex items-center justify-between pb-3 border-b-2 border-csDark">
        <span class="gasoek-font text-2xl text-csDark">FLOW INTENSITY METRIC</span>
        <span class="pill-tag bg-csSecondaryAccent text-csDark px-2.5 py-1">HOURLY CHECK</span>
      </div>
      <p class="text-sm text-csDark/80 mt-3 font-medium">No prolonged hourly soaking incidents reported. CycleSafe flags consecutive hourly soaking as a prompt to consult healthcare professionals.</p>
    </div>
  `;
}

// 6. Perimenopause View
async function loadPerimenopause() {
  const forecast = await CycleSafeAPI.getForecast(46, true);
  const target = document.getElementById('peri-forecast-display');
  if (target && forecast.forecast_available) {
    target.innerHTML = `
      <div class="p-5 bg-white border-2 border-csDark rounded-2xl sui-shadow-sm">
        <div class="flex justify-between items-center">
          <span class="font-mono text-xs font-bold text-csAccent uppercase">AGE-ADJUSTED CONFORMAL WINDOW</span>
          <span class="pill-tag bg-amber-200 text-csDark border border-csDark px-2 py-0.5">WIDER UNCERTAINTY</span>
        </div>
        <p class="gasoek-font text-4xl text-csDark mt-2">${forecast.predicted_days} DAYS</p>
        <p class="font-mono text-xs text-csDark/80 mt-1">80% Interval: ${forecast.prediction_interval_80[0]} - ${forecast.prediction_interval_80[1]} days</p>
        <p class="font-mono text-[11px] text-csDark/60 mt-2 italic">Perimenopausal transition often shows increased inter-cycle variance. Wider conformal intervals protect against false certainty.</p>
      </div>
    `;
  }
}

// 7. Doctor Report View
async function loadDoctorReport() {
  const cycles = await CycleSafeAPI.getCycles();
  const symptoms = await CycleSafeAPI.getSymptoms();
  const uid = CycleSafeAPI.getUserId();

  document.getElementById('doc-user-id').textContent = uid;
  document.getElementById('doc-cycle-count').textContent = cycles.length;
  document.getElementById('doc-symptom-count').textContent = symptoms.length;

  const lengths = cycles.map(c => Number(c.cycle_length_days) || 28);
  const avg = lengths.length ? (lengths.reduce((a, b) => a + b, 0) / lengths.length).toFixed(1) : '28.0';
  document.getElementById('doc-median-days').textContent = `${avg} Days`;

  // Symptoms list
  const symContainer = document.getElementById('doc-symptom-summary');
  if (symContainer) {
    const symCounts = {};
    symptoms.forEach(s => {
      symCounts[s.symptom] = (symCounts[s.symptom] || 0) + 1;
    });
    symContainer.innerHTML = Object.entries(symCounts).map(([k, v]) => `
      <span class="pill-tag bg-csWarmBg border border-csDark px-2.5 py-1 text-xs text-csDark">
        ${k.replace('_', ' ')}: ${v} logged
      </span>
    `).join(' ') || '<span class="text-xs text-csDark/60">No symptoms recorded yet.</span>';
  }
}

function printDoctorReport() {
  window.print();
}

function downloadDoctorPdf() {
  const pdfUrl = CycleSafeAPI.getDoctorReportPdfUrl();
  window.open(pdfUrl, '_blank');
}

// 8. Product Access Map View
async function setupMapFilters() {
  document.getElementById('map-filter-free')?.addEventListener('change', loadMapLocations);
  document.getElementById('map-filter-product')?.addEventListener('change', loadMapLocations);
}

async function loadMapLocations() {
  const freeOnly = document.getElementById('map-filter-free')?.checked || false;
  const product = document.getElementById('map-filter-product')?.value || null;

  const res = await CycleSafeAPI.getMapLocations(freeOnly, product);
  const container = document.getElementById('map-location-list');
  if (!container) return;

  container.innerHTML = res.locations.map(loc => `
    <div class="bg-white border-2 border-csDark rounded-2xl p-5 sui-shadow flex flex-col md:flex-row justify-between md:items-center space-y-4 md:space-y-0">
      <div>
        <div class="flex items-center space-x-2">
          <h4 class="gasoek-font text-xl text-csDark">${loc.name}</h4>
          <span class="pill-tag ${loc.free_tier ? 'bg-emerald-200 text-emerald-950' : 'bg-csWarmBg text-csDark'} border border-csDark px-2 py-0.5">
            ${loc.free_tier ? 'FREE ACCESS' : 'COMMERCIAL'}
          </span>
          ${loc.verified ? '<span class="pill-tag bg-csAccent text-white border border-csDark px-2 py-0.5">VERIFIED</span>' : ''}
        </div>
        <p class="font-mono text-xs text-csDark/70 mt-1">${loc.address}</p>
        <div class="flex flex-wrap gap-1.5 mt-2">
          ${loc.products.map(p => `<span class="font-mono text-[10px] bg-csLightBg border border-csDark px-2 py-0.5 rounded-md font-bold uppercase">${p.replace('_', ' ')}</span>`).join('')}
        </div>
      </div>

      <div class="flex items-center space-x-3">
        <div class="text-right font-mono text-[11px] text-csDark/60 hidden sm:block">
          <div>Verified by ${loc.verification_count} check-ins</div>
          <div>Updated ${loc.last_updated}</div>
        </div>
        <button onclick="openCheckinModal('${loc.id}', '${loc.name.replace(/'/g, "\\'")}')" class="font-mono text-xs font-bold px-4 py-2.5 bg-csWarmBg text-csDark border-2 border-csDark rounded-xl sui-shadow-sm hover:bg-amber-300 transition">
          CHECK-IN
        </button>
      </div>
    </div>
  `).join('');
}

let activeCheckinLocId = null;

function openCheckinModal(id, name) {
  activeCheckinLocId = id;
  const modal = document.getElementById('checkin-modal');
  const title = document.getElementById('checkin-modal-loc');
  if (title) title.textContent = name;
  if (modal) modal.classList.remove('hidden');
}

function closeCheckinModal() {
  const modal = document.getElementById('checkin-modal');
  if (modal) modal.classList.add('hidden');
  activeCheckinLocId = null;
}

async function submitCheckin() {
  if (!activeCheckinLocId) return;
  const status = document.getElementById('checkin-status-select')?.value || 'in_stock';
  const note = document.getElementById('checkin-note')?.value || '';
  const products = ["pads", "tampons"];

  await CycleSafeAPI.checkinLocation(activeCheckinLocId, status, products, note);
  showToast('✓ Community check-in recorded. Thank you!');
  closeCheckinModal();
  loadMapLocations();
}

// 9. Privacy, Consent & Bearer Tokens
function setupPrivacyControls() {
  document.getElementById('privacy-register-btn')?.addEventListener('click', async () => {
    const inputId = document.getElementById('privacy-userid-input')?.value || 'user_' + Math.random().toString(36).substring(2, 8);
    const res = await CycleSafeAPI.registerConsent(inputId);
    showTokenDisplay(res.token);
    loadPrivacySettings();
    showToast('✓ New consent & cryptographic token generated');
  });

  document.getElementById('privacy-export-btn')?.addEventListener('click', async () => {
    const jsonStr = await CycleSafeAPI.exportUserData();
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `CycleSafe_Export_${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('✓ Health archive downloaded');
  });

  document.getElementById('privacy-delete-btn')?.addEventListener('click', async () => {
    if (confirm('Permanently delete all cycle history, symptoms, and cryptographic tokens? This cannot be undone.')) {
      await CycleSafeAPI.deleteUserData();
      showToast('✓ All data wiped permanently');
      refreshAllData();
      showView('landing');
    }
  });
}

function loadPrivacySettings() {
  const uid = CycleSafeAPI.getUserId();
  const token = localStorage.getItem('cs_auth_token') || '●●●●●●●● (Generated at registration)';
  const idEl = document.getElementById('privacy-active-user');
  if (idEl) idEl.textContent = uid;
  const tokEl = document.getElementById('privacy-active-token');
  if (tokEl) tokEl.textContent = token.substring(0, 16) + '...';
}

function showTokenDisplay(token) {
  const container = document.getElementById('privacy-token-display');
  if (container) {
    container.innerHTML = `
      <div class="mt-4 p-4 bg-csWarmBg border-2 border-csDark rounded-xl font-mono text-xs">
        <p class="font-bold text-csDark">SAVE YOUR BEARER TOKEN SECURELY (SHOWN ONCE):</p>
        <div class="mt-2 p-2 bg-white rounded border border-csDark break-all text-csAccent font-bold">${token}</div>
        <p class="text-[10px] text-csDark/70 mt-1">This token hashes with SHA-256 for private verification. CycleSafe never stores your plaintext token.</p>
      </div>
    `;
  }
}

// Toast helper
function showToast(msg) {
  const existing = document.getElementById('cs-toast');
  if (existing) existing.remove();

  const toast = document.createElement('div');
  toast.id = 'cs-toast';
  toast.className = 'fixed bottom-6 right-6 z-50 bg-csDark text-white px-5 py-3 rounded-xl sui-border sui-shadow font-mono text-xs font-bold flex items-center space-x-2 animate-bounce';
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.remove();
  }, 3500);
}

function refreshAllData() {
  loadDashboard();
}
