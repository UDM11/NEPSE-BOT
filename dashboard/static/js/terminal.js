// Live Feed Updates (Watcher table) with low latency DOM flashing
window.updateLiveFeed = function(data) {
    if (!data.watchlist) return;
    const tbody = document.getElementById('live-watcher-tbody');
    if (!tbody) return;
    
    if (data.watchlist.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-secondary)">No active quote watchers running. Arm system to begin monitoring.</td></tr>`;
        return;
    }

    // Remove placeholder if present
    const firstRow = tbody.firstElementChild;
    if (firstRow && firstRow.cells.length === 1) {
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
        const totalDepth = s.bid_quantity + s.ask_quantity;
        const bidRatio = totalDepth > 0 ? (s.bid_quantity / totalDepth * 100) : 0;
        
        const statusText = s.is_at_upper_circuit ? 'CIRCUIT LIMIT HIT' : 'MONITORING TICKS';
        const badgeClass = s.is_at_upper_circuit ? 'badge-danger' : 'badge-success';

        const rowId = `row-${s.symbol}`;
        let row = existingRows[s.symbol];

        if (!row) {
            // Create new row
            row = document.createElement('tr');
            row.id = rowId;
            row.innerHTML = `
                <td><span class="symbol-badge">${s.symbol}</span></td>
                <td class="price-cell">
                    <strong class="ltp-val" style="font-size:1rem;">${displayLtp.toFixed(1)}</strong> 
                    <span class="change-val" style="font-size:0.75rem; font-weight:600; margin-left:0.25rem;"></span>
                </td>
                <td class="bid-qty-cell" style="font-family:var(--font-mono); font-weight:500;">${s.bid_quantity.toLocaleString()}</td>
                <td class="depth-cell">
                    <div class="depth-bar-container">
                        <div class="depth-bar-fill" style="width: ${bidRatio}%"></div>
                        <span class="depth-text">${bidRatio.toFixed(0)}% BID</span>
                    </div>
                </td>
                <td class="ask-qty-cell" style="font-family:var(--font-mono); font-weight:500;">${s.ask_quantity.toLocaleString()}</td>
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

        // Check Bid Qty change
        const oldBid = parseInt(bidEl.textContent.replace(/,/g, '')) || 0;
        if (oldBid !== s.bid_quantity) {
            bidEl.textContent = s.bid_quantity.toLocaleString();
            bidEl.classList.remove('flash-info');
            void bidEl.offsetWidth; // Trigger reflow
            bidEl.classList.add('flash-info');
        }

        // Check Ask Qty change
        const oldAsk = parseInt(askEl.textContent.replace(/,/g, '')) || 0;
        if (oldAsk !== s.ask_quantity) {
            askEl.textContent = s.ask_quantity.toLocaleString();
            askEl.classList.remove('flash-info');
            void askEl.offsetWidth; // Trigger reflow
            askEl.classList.add('flash-info');
        }

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
