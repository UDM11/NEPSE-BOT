// Sync watchlist configuration from server
window.loadWatchlist = async function() {
    try {
        const response = await fetch('/api/watchlist/config');
        const data = await response.json();
        window.globalState.watchlistData = data.symbols || [];
        window.renderWatchlistEditor();
        window.showToast("YAML Watchlist synced successfully.");
    } catch (err) {
        window.showToast("Failed to fetch watchlist config.", "error");
    }
};

// Render Watchlist Editor rows dynamically
window.renderWatchlistEditor = function() {
    const tbody = document.getElementById('watchlist-editable-tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    
    const dataList = window.globalState.watchlistData;
    
    if (dataList.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-muted)">No symbols configured. Use the fields above to add one.</td></tr>`;
        return;
    }

    dataList.forEach((item, index) => {
        const tr = document.createElement('tr');
        const stratName = item.strategy === 'ipo_daily_circuit' ? 'IPO Staging' : 'Breakout';
        tr.innerHTML = `
            <td><span class="symbol-badge">${item.symbol}</span></td>
            <td>
                <input type="number" class="table-input" value="${item.quantity}" min="1" 
                    onchange="window.updateLocalItem(${index}, 'quantity', this.value)">
            </td>
            <td>
                <input type="number" class="table-input" value="${item.prev_close}" min="0.1" step="0.1" 
                    onchange="window.updateLocalItem(${index}, 'prev_close', this.value)">
            </td>
            <td>
                <input type="number" class="table-input" value="${item.circuit_percentage}" min="1" max="100" 
                    onchange="window.updateLocalItem(${index}, 'circuit_percentage', this.value)">
            </td>
            <td><span style="font-weight:600; font-size: 0.8rem; color:var(--text-secondary);">${stratName}</span></td>
            <td>
                <input type="checkbox" ${item.is_ipo ? 'checked' : ''} style="cursor:pointer; scale:1.1;"
                    onchange="window.updateLocalItem(${index}, 'is_ipo', this.checked)">
            </td>
            <td>
                <span class="badge ${item.enabled ? 'badge-success' : 'badge-danger'}" style="cursor:pointer; min-width:80px;"
                    onclick="window.toggleItemEnabled(${index})">
                    ${item.enabled ? 'Enabled' : 'Disabled'}
                </span>
            </td>
            <td>
                <button class="btn btn-danger" style="padding: 0.3rem 0.6rem; font-size: 0.725rem" 
                    onclick="window.deleteLocalItem(${index})">Delete</button>
            </td>
        `;
        tbody.appendChild(tr);
    });
};

// Update local cache item field values
window.updateLocalItem = function(index, key, val) {
    const list = window.globalState.watchlistData;
    if (key === 'quantity') list[index].quantity = parseInt(val) || 10;
    else if (key === 'prev_close') list[index].prev_close = parseFloat(val) || 0.0;
    else if (key === 'circuit_percentage') list[index].circuit_percentage = parseFloat(val) || 15.0;
    else if (key === 'is_ipo') list[index].is_ipo = !!val;
};

// Toggle active status
window.toggleItemEnabled = function(index) {
    window.globalState.watchlistData[index].enabled = !window.globalState.watchlistData[index].enabled;
    window.renderWatchlistEditor();
};

// Delete symbol locally
window.deleteLocalItem = function(index) {
    const sym = window.globalState.watchlistData[index].symbol;
    window.globalState.watchlistData.splice(index, 1);
    window.renderWatchlistEditor();
    window.showToast(`Deleted ${sym} locally. Click "Save to watchlist.yaml" to apply permanently.`, "warn");
    window.playAlert('warning');
};

// Add watchlist stock item from form fields
window.addNewWatchlistItem = function() {
    const symbolEl = document.getElementById('form-symbol');
    const qtyEl = document.getElementById('form-qty');
    const prevEl = document.getElementById('form-prev');
    const circuitEl = document.getElementById('form-circuit');
    const strategyEl = document.getElementById('form-strategy');

    const symbol = symbolEl.value.trim().toUpperCase();
    const quantity = parseInt(qtyEl.value);
    const prev_close = parseFloat(prevEl.value);
    const circuit_percentage = parseFloat(circuitEl.value) || 15.0;
    const strategy = strategyEl.value;

    if (!symbol || isNaN(quantity) || isNaN(prev_close)) {
        window.showToast("Please provide Symbol, Quantity, and Prev Close.", "warn");
        window.playAlert('warning');
        return;
    }

    if (window.globalState.watchlistData.some(item => item.symbol === symbol)) {
        window.showToast(`${symbol} already exists in watchlist.`, "warn");
        window.playAlert('warning');
        return;
    }

    window.globalState.watchlistData.push({
        symbol: symbol,
        quantity: quantity,
        prev_close: prev_close,
        circuit_percentage: circuit_percentage,
        strategy: strategy,
        is_ipo: strategy === 'ipo_daily_circuit',
        enabled: true
    });

    // Reset fields
    symbolEl.value = '';
    qtyEl.value = '10';
    prevEl.value = '';
    circuitEl.value = '15';

    window.renderWatchlistEditor();
    window.showToast(`Added ${symbol} locally.`, "success");
    window.playAlert('connect');
};

// Save changes back to server
window.saveWatchlistToServer = async function() {
    try {
        const response = await fetch('/api/watchlist/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbols: window.globalState.watchlistData })
        });
        const res = await response.json();
        if (res.status === 'success') {
            window.showToast("Watchlist written to watchlist.yaml successfully!", "success");
            window.playAlert('success');
        } else {
            window.showToast("Failed to write to watchlist.yaml: " + res.message, "error");
            window.playAlert('error');
        }
    } catch (err) {
        window.showToast("Network failure saving watchlist config.", "error");
        window.playAlert('error');
    }
};

// Arm preemptive staging
window.armAndExecuteBot = async function() {
    const btn = document.querySelector('.btn-arm-system');
    const oldText = btn.textContent;
    btn.textContent = "ARMING ENGINE...";
    btn.style.pointerEvents = 'none';
    btn.style.opacity = '0.6';

    try {
        const response = await fetch('/api/execute', { method: 'POST' });
        const res = await response.json();
        if (res.status === 'success') {
            window.showToast("System armed! Staging modules running headlessly.", "success");
            window.playAlert('success');
            
            btn.textContent = "SYSTEM ARMED";
            btn.style.background = 'linear-gradient(135deg, var(--accent-emerald) 0%, #065f46 100%)';
            btn.style.boxShadow = '0 0 30px rgba(16, 185, 129, 0.4)';
            
            setTimeout(() => {
                btn.textContent = "Arm Preemptive Staging";
                btn.style.background = '';
                btn.style.boxShadow = '';
                btn.style.opacity = '1';
                btn.style.pointerEvents = 'auto';
            }, 4000);
        } else {
            window.showToast("Failed to arm system: " + res.message, "error");
            window.playAlert('error');
            btn.textContent = oldText;
            btn.style.opacity = '1';
            btn.style.pointerEvents = 'auto';
        }
    } catch (err) {
        window.showToast("Connection timed out arming preemptive engine.", "error");
        window.playAlert('error');
        btn.textContent = oldText;
        btn.style.opacity = '1';
        btn.style.pointerEvents = 'auto';
    }
};
