// Live Feed Updates (Watcher table) with low latency DOM flashing
window.updateLiveFeed = function(data) {
    // Update NEPSE index bar if data present
    if (data.nepse_index) {
        updateNepseIndexBar(data.nepse_index);
    }
    // Always update date/time clock
    updateTickerClock();

    if (!data.watchlist) return;
    const tbody = document.getElementById('live-watcher-tbody');
    if (!tbody) return;
    
    if (data.watchlist.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-secondary)">No active quote watchers running. Arm system to begin monitoring.</td></tr>`;
        return;
    }

    // Remove placeholder if present
    const firstRow = tbody.firstElementChild;
    if (firstRow && firstRow.cells.length <= 2) {
        tbody.innerHTML = '';
    }

    // Map existing row elements by symbol
    const existingRows = {};
    Array.from(tbody.children).forEach(row => {
        const symBadge = row.querySelector('.symbol-badge');
        if (symBadge) {
            existingRows[symBadge.textContent.trim()] = row;
        }
    });

    data.watchlist.forEach(s => {
        const displayLtp = s.ltp > 0 ? s.ltp : s.prev_close;
        const pctChange = (s.prev_close > 0 && s.ltp > 0) ? ((s.ltp - s.prev_close) / s.prev_close * 100) : 0.0;
        const totalDepth = (s.bid_quantity || 0) + (s.ask_quantity || 0);
        const bidRatio = totalDepth > 0 ? (s.bid_quantity / totalDepth * 100) : 0;
        const bidDisplay = s.bid_quantity > 0 ? s.bid_quantity.toLocaleString() : '<span style="color:var(--text-muted)">—</span>';
        const askDisplay = s.ask_quantity > 0 ? s.ask_quantity.toLocaleString() : '<span style="color:var(--text-muted)">—</span>';
        const volDisplay = s.volume > 0 ? s.volume.toLocaleString() : '<span style="color:var(--text-muted)">—</span>';
        
        const statusText = s.is_at_upper_circuit ? 'CIRCUIT LIMIT HIT' : 'MONITORING TICKS';
        const badgeClass = s.is_at_upper_circuit ? 'badge-danger' : 'badge-success';

        const rowId = `row-${s.symbol}`;
        let row = existingRows[s.symbol];

        if (!row) {
            // Create new row (8 columns now — added Volume)
            row = document.createElement('tr');
            row.id = rowId;
            row.innerHTML = `
                <td><span class="symbol-badge">${s.symbol}</span></td>
                <td class="price-cell">
                    <strong class="ltp-val" style="font-size:1rem;">${displayLtp.toFixed(1)}</strong> 
                    <span class="change-val" style="font-size:0.75rem; font-weight:600; margin-left:0.25rem;"></span>
                </td>
                <td class="bid-qty-cell" style="font-family:var(--font-mono); font-weight:500;">${bidDisplay}</td>
                <td class="depth-cell">
                    <div class="depth-bar-container">
                        <div class="depth-bar-fill" style="width: ${bidRatio}%"></div>
                        <span class="depth-text">${bidRatio.toFixed(0)}% BID</span>
                    </div>
                </td>
                <td class="ask-qty-cell" style="font-family:var(--font-mono); font-weight:500;">${askDisplay}</td>
                <td class="vol-cell" style="font-family:var(--font-mono); color:var(--text-secondary);">${volDisplay}</td>
                <td class="circuit-cell">
                    <span style="color: var(--accent-cyan); font-family:var(--font-mono); font-weight:600;">
                        ${s.upper_circuit.toFixed(1)}
                    </span>
                </td>
                <td class="status-cell">
                    <span class="badge ${badgeClass}">
                        <span class="status-dot"></span> <span class="status-txt">${statusText}</span>
                    </span>
                </td>
            `;
            tbody.appendChild(row);
        }

        // Update row values and trigger flash if changed
        const ltpEl = row.querySelector('.ltp-val');
        const changeEl = row.querySelector('.change-val');
        const bidEl = row.querySelector('.bid-qty-cell');
        const askEl = row.querySelector('.ask-qty-cell');
        const volEl = row.querySelector('.vol-cell');
        const depthBar = row.querySelector('.depth-bar-fill');
        const depthText = row.querySelector('.depth-text');
        const statusBadge = row.querySelector('.status-cell .badge');
        const statusTxt = row.querySelector('.status-txt');

        // Check LTP change
        const oldLtp = parseFloat(ltpEl.textContent);
        const newLtp = parseFloat(displayLtp.toFixed(1));
        if (oldLtp !== newLtp) {
            ltpEl.textContent = displayLtp.toFixed(1);
            const cell = ltpEl.parentElement;
            cell.classList.remove('flash-up', 'flash-down');
            void cell.offsetWidth; // Trigger reflow
            cell.classList.add(newLtp >= oldLtp ? 'flash-up' : 'flash-down');
        }

        // Update percent change element
        changeEl.textContent = `${pctChange >= 0 ? '▲' : '▼'} ${Math.abs(pctChange).toFixed(1)}%`;
        changeEl.style.color = pctChange >= 0 ? 'var(--accent-emerald)' : 'var(--accent-rose)';

        // Update Bid/Ask qty
        bidEl.innerHTML = bidDisplay;
        askEl.innerHTML = askDisplay;
        if (volEl) volEl.innerHTML = volDisplay;

        // Update depth bar
        depthBar.style.width = `${bidRatio}%`;
        depthText.textContent = `${bidRatio.toFixed(0)}% BID`;

        // Update status badge
        if (statusTxt.textContent !== statusText) {
            statusTxt.textContent = statusText;
            statusBadge.className = `badge ${badgeClass}`;
        }
    });

    // Clean up rows that are no longer in watchlist
    const currentSymbols = new Set(data.watchlist.map(s => s.symbol));
    Array.from(tbody.children).forEach(row => {
        const symBadge = row.querySelector('.symbol-badge');
        if (symBadge && !currentSymbols.has(symBadge.textContent.trim())) {
            row.remove();
        }
    });
};

// Update NEPSE Index ticker bar
function updateNepseIndexBar(idx) {
    if (!idx) return;

    const fmt = (v) => v != null ? parseFloat(v).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '--';
    const fmtInt = (v) => v != null ? parseInt(v).toLocaleString('en-US') : '--';
    
    // Update main NEPSE Index
    if (idx.nepse) {
        const valEl = document.getElementById('ticker-nepse-val');
        const chgEl = document.getElementById('ticker-nepse-chg');
        const pctEl = document.getElementById('ticker-nepse-pct');
        const itemEl = document.getElementById('ticker-nepse');
        
        if (valEl) valEl.textContent = fmt(idx.nepse.value);
        
        const change = parseFloat(idx.nepse.points_change || 0);
        const changePct = parseFloat(idx.nepse.change || 0);
        
        if (chgEl) chgEl.textContent = (change >= 0 ? '+' : '') + change.toFixed(2);
        if (pctEl) pctEl.textContent = (changePct >= 0 ? '+' : '') + changePct.toFixed(2) + '%';
        
        if (itemEl) {
            itemEl.className = 'ticker-index-block ' + (change > 0 ? 'positive' : (change < 0 ? 'negative' : 'neutral'));
            const arrowEl = itemEl.querySelector('.tib-arrow');
            if (arrowEl) arrowEl.textContent = change >= 0 ? '▲' : '▼';
        }
        
        // Volume and Turnover
        const volVal = document.getElementById('ticker-vol-val');
        if (volVal) volVal.textContent = fmtInt(idx.nepse.volume);
        
        const turnVal = document.getElementById('ticker-turn-val');
        if (turnVal && idx.nepse.turnover !== undefined) {
            const tVal = parseFloat(idx.nepse.turnover);
            if (!isNaN(tVal)) {
                if (tVal >= 1000000000) {
                    turnVal.textContent = `Rs. ${(tVal / 1000000000).toFixed(2)}B`;
                } else if (tVal >= 10000000) {
                    turnVal.textContent = `Rs. ${(tVal / 10000000).toFixed(2)} Cr`;
                } else {
                    turnVal.textContent = `Rs. ${tVal.toLocaleString('en-US', {maximumFractionDigits: 0})}`;
                }
            } else {
                turnVal.textContent = '--';
            }
        }
    }
    
    // Update Sensitive Index (SENSIND)
    if (idx.sensitive) {
        const valEl = document.getElementById('ticker-sensind-val');
        const chgEl = document.getElementById('ticker-sensind-chg');
        const pctEl = document.getElementById('ticker-sensind-pct');
        const itemEl = document.getElementById('ticker-sensind');
        
        if (valEl) valEl.textContent = fmt(idx.sensitive.value);
        
        const change = parseFloat(idx.sensitive.points_change || 0);
        const changePct = parseFloat(idx.sensitive.change || 0);
        
        if (chgEl) chgEl.textContent = (change >= 0 ? '+' : '') + change.toFixed(2);
        if (pctEl) pctEl.textContent = (changePct >= 0 ? '+' : '') + changePct.toFixed(2) + '%';
        
        if (itemEl) {
            itemEl.className = 'ticker-index-block ' + (change > 0 ? 'positive' : (change < 0 ? 'negative' : 'neutral'));
            const arrowEl = itemEl.querySelector('.tib-arrow');
            if (arrowEl) arrowEl.textContent = change >= 0 ? '▲' : '▼';
        }
    }
    
    // Update Watchlist Ticker scroller
    if (idx.scrips && idx.scrips.length > 0) {
        const scripsContainer = document.getElementById('ticker-scrips-container');
        if (scripsContainer) {
            scripsContainer.innerHTML = '';
            idx.scrips.forEach(s => {
                const change = parseFloat(s.change || 0);
                const sign = change >= 0 ? '+' : '';
                const itemClass = change > 0 ? 'positive' : (change < 0 ? 'negative' : 'neutral');
                scripsContainer.innerHTML += `
                    <div class="ticker-scrip-item ${itemClass}">
                        <span class="ticker-scrip-name">${s.symbol}</span>
                        <span class="ticker-scrip-val">${fmt(s.ltp)}</span>
                        <span class="ticker-scrip-chg">(${sign}${change.toFixed(2)}%)</span>
                    </div>
                `;
            });
        }
    }
    
    // Update Market Status
    if (idx.market_status) {
        const statusEl = document.getElementById('ticker-market-status');
        if (statusEl) {
            const statusUpper = idx.market_status.toUpperCase();
            statusEl.textContent = statusUpper;
            statusEl.className = statusUpper.includes('OPEN') ? 'status-open' : 'status-close';
        }
    }
    
}

// ========================
// NTP-Style Clock Sync System
// ========================
// Fetches server time, calculates offset, and corrects the displayed clock
// so even if local system is 1-2 seconds off, the dashboard shows exact time.

window._clockSync = {
    offsetMs: 0,          // Server time minus local time (milliseconds)
    isSynced: false,
    lastSyncAt: null,
    driftMs: 0,
    syncCount: 0,
};

// Single round-trip time measurement
async function _measureTimeOffset() {
    const t1 = performance.now();
    const localSendMs = Date.now();
    
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 3000);
    const r = await fetch('/api/time', { signal: controller.signal });
    clearTimeout(timeoutId);
    
    const t2 = performance.now();
    const data = await r.json();
    
    const roundTripMs = t2 - t1;
    const serverMs = data.unix_ms;
    // Estimate: server time at midpoint of request
    const localMidpointMs = localSendMs + (roundTripMs / 2);
    const offset = serverMs - localMidpointMs;
    
    return { offset, roundTripMs };
}

// Perform NTP sync with multiple samples for accuracy
async function syncClockWithServer() {
    const badge = document.getElementById('ticker-sync-badge');
    if (badge) {
        badge.className = 'sync-badge syncing';
        badge.textContent = '⟳ SYNCING';
    }
    
    try {
        // Take 3 samples, use the one with lowest round-trip (most accurate)
        const samples = [];
        for (let i = 0; i < 3; i++) {
            try {
                const sample = await _measureTimeOffset();
                samples.push(sample);
            } catch(e) { /* skip failed sample */ }
            if (i < 2) await new Promise(r => setTimeout(r, 150));
        }
        
        if (samples.length === 0) {
            throw new Error('All samples failed');
        }
        
        // Pick the sample with lowest round-trip time (most accurate)
        samples.sort((a, b) => a.roundTripMs - b.roundTripMs);
        const best = samples[0];
        
        window._clockSync.offsetMs = best.offset;
        window._clockSync.driftMs = Math.abs(best.offset);
        window._clockSync.isSynced = true;
        window._clockSync.lastSyncAt = Date.now();
        window._clockSync.syncCount++;
        
        // Update badge
        if (badge) {
            const driftSec = (window._clockSync.driftMs / 1000).toFixed(1);
            if (window._clockSync.driftMs < 500) {
                badge.className = 'sync-badge synced';
                badge.textContent = `✓ SYNCED`;
                badge.title = `Clock synced | Drift: ${driftSec}s | RTT: ${best.roundTripMs.toFixed(0)}ms`;
            } else if (window._clockSync.driftMs < 2000) {
                badge.className = 'sync-badge synced';
                badge.textContent = `✓ ${driftSec}s`;
                badge.title = `Clock drift: ${driftSec}s corrected | RTT: ${best.roundTripMs.toFixed(0)}ms`;
            } else {
                badge.className = 'sync-badge drift';
                badge.textContent = `⚠ DRIFT ${driftSec}s`;
                badge.title = `WARNING: High clock drift ${driftSec}s detected! Sync your system clock.`;
            }
        }
        
        console.info(`[ClockSync] Synced. Offset: ${best.offset.toFixed(1)}ms, RTT: ${best.roundTripMs.toFixed(0)}ms, Samples: ${samples.length}`);
    } catch(e) {
        console.warn('[ClockSync] Sync failed:', e.message);
        if (badge && !window._clockSync.isSynced) {
            badge.className = 'sync-badge drift';
            badge.textContent = '✕ UNSYNC';
            badge.title = 'Time sync failed. Using local system clock.';
        }
    }
}

// Get the corrected "real" time using sync offset
function getSyncedNow() {
    return new Date(Date.now() + window._clockSync.offsetMs);
}

// Update Ticker clock time using synced time
function updateTickerClock() {
    const dateEl = document.getElementById('ticker-date');
    const timeEl = document.getElementById('ticker-time');
    const now = getSyncedNow();
    const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const dayName = days[now.getDay()];
    const monthName = months[now.getMonth()];
    const dateNum = now.getDate();
    const year = now.getFullYear();
    if (dateEl) {
        dateEl.textContent = `${dayName}, ${dateNum} ${monthName} ${year}`;
    }
    if (timeEl) {
        const pad = (n) => String(n).padStart(2, '0');
        const h = now.getHours();
        const m = now.getMinutes();
        const s = now.getSeconds();
        const ampm = h >= 12 ? 'PM' : 'AM';
        const h12 = h % 12 || 12;
        timeEl.textContent = `${pad(h12)}:${pad(m)}:${pad(s)} ${ampm}`;
    }
}

// Initial sync on page load, then tick every 100ms for smooth seconds, re-sync every 60s
syncClockWithServer();
updateTickerClock();
setInterval(updateTickerClock, 200);
setInterval(syncClockWithServer, 60000);

// Fetch NEPSE index on page load via REST API fallback (with timeout)
(async function fetchNepseIndexOnLoad() {
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 8000);
        const r = await fetch('/api/nepse-index', { signal: controller.signal });
        clearTimeout(timeoutId);
        if (r.ok) {
            const data = await r.json();
            updateNepseIndexBar(data);
        }
    } catch(e) {
        console.debug('NEPSE index initial fetch skipped (market likely closed):', e.name);
    }
})();
