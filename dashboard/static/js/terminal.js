// Live Feed Updates (Watcher table) with low latency DOM flashing
window.updateLiveFeed = function(data) {
    // Update NEPSE index bar if data present
    if (data.nepse_index) {
        updateNepseIndexBar(data.nepse_index);
    }

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
    const fmt = (v) => v != null ? parseFloat(v).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '--';
    const fmtInt = (v) => v != null ? parseInt(v).toLocaleString('en-US') : '--';
    const fmtChg = (v) => {
        if (v == null) return { text: '--%', color: '#63b3ed', bg: 'rgba(99,179,237,0.15)' };
        const n = parseFloat(v);
        const sign = n >= 0 ? '▲' : '▼';
        const color = n >= 0 ? '#48bb78' : '#fc8181';
        const bg = n >= 0 ? 'rgba(72,187,120,0.15)' : 'rgba(252,129,129,0.15)';
        return { text: `${sign} ${Math.abs(n).toFixed(2)}%`, color, bg };
    };
    const fmtPts = (v) => {
        if (v == null) return { text: '--', color: '#63b3ed', bg: 'rgba(99,179,237,0.15)' };
        const n = parseFloat(v);
        const prefix = n >= 0 ? '+' : '';
        const color = n >= 0 ? '#48bb78' : '#fc8181';
        const bg = n >= 0 ? 'rgba(72,187,120,0.15)' : 'rgba(252,129,129,0.15)';
        return { text: `${prefix}${n.toFixed(2)}`, color, bg };
    };

    if (idx.nepse) {
        const chg = fmtChg(idx.nepse.change);
        const pts = fmtPts(idx.nepse.points_change);
        const el = document.getElementById('idx-nepse-val');
        const chgEl = document.getElementById('idx-nepse-chg');
        const ptsEl = document.getElementById('idx-nepse-pts');
        const volEl = document.getElementById('idx-volume-val');
        const turnEl = document.getElementById('idx-turnover-val');
        
        if (el) el.textContent = fmt(idx.nepse.value);
        if (chgEl) { chgEl.textContent = chg.text; chgEl.style.color = chg.color; chgEl.style.background = chg.bg; }
        if (ptsEl) { ptsEl.textContent = pts.text; ptsEl.style.color = pts.color; ptsEl.style.background = pts.bg; }
        
        if (volEl) volEl.textContent = fmtInt(idx.nepse.volume);
        if (turnEl) {
            const turnoverVal = parseFloat(idx.nepse.turnover);
            if (!isNaN(turnoverVal)) {
                if (turnoverVal >= 1000000000) {
                    turnEl.textContent = `Rs. ${(turnoverVal / 1000000000).toFixed(2)}B`;
                } else if (turnoverVal >= 10000000) {
                    turnEl.textContent = `Rs. ${(turnoverVal / 10000000).toFixed(2)} Cr`;
                } else {
                    turnEl.textContent = `Rs. ${turnoverVal.toLocaleString('en-US', {maximumFractionDigits: 0})}`;
                }
            } else {
                turnEl.textContent = '--';
            }
        }
    }
    const upd = document.getElementById('idx-last-update');
    if (upd) upd.textContent = 'Updated ' + new Date().toLocaleTimeString('en-US', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
}

// Fetch NEPSE index on page load via REST API fallback
(async function fetchNepseIndexOnLoad() {
    try {
        const r = await fetch('/api/nepse-index');
        if (r.ok) {
            const data = await r.json();
            updateNepseIndexBar(data);
        }
    } catch(e) {}
})();
