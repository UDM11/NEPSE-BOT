// Load Risk Panel and System status info
window.fetchSystemHealth = async function() {
    try {
        const response = await fetch('/api/risk');
        const d = await response.json();
        
        const badge = document.getElementById('risk-badge');
        const mobileBadge = document.getElementById('mobile-risk-badge');
        [badge, mobileBadge].forEach(el => {
            if (el) {
                if (d.kill_switch_active) {
                    el.innerHTML = '<span class="status-dot"></span> KILL SWITCH HALT';
                    el.className = 'badge badge-danger';
                } else {
                    el.innerHTML = '<span class="status-dot"></span> Risk Guard Active';
                    el.className = 'badge badge-success';
                }
            }
        });

        // Update exposure card
        const exposureEl = document.getElementById('stat-exposure');
        if (exposureEl) {
            exposureEl.textContent = `${d.current_exposure ? d.current_exposure.toLocaleString() : 0} / ${d.max_exposure ? d.max_exposure.toLocaleString() : 100000}`;
        }
    } catch (err) {
        console.error("Failed to fetch system health: ", err);
    }
};

// Emergency Kill Switch Activation
window.emergencyKillSwitch = async function() {
    if (confirm("CRITICAL: Force activation of system-wide trading kill switch? Staging triggers and active execution loops will be halted immediately!")) {
        await fetch('/api/kill-switch/activate', { method: 'POST' });
        window.showToast("CRITICAL: Kill switch activated! Automated trading loops HALTED.", "error");
        window.playAlert('error');
        window.fetchSystemHealth();
    }
};

// Reset Kill Switch
window.resetKillSwitch = async function() {
    await fetch('/api/kill-switch/deactivate', { method: 'POST' });
    window.showToast("System Reset. Emergency Kill Switch deactivated.");
    window.playAlert('connect');
    window.fetchSystemHealth();
};

// Fetch Secondary Info (Recent signals and orders logs)
window.fetchSecondaryInfo = async function() {
    try {
        // Fetch Signals
        const sigResponse = await fetch('/api/signals');
        const sigData = await sigResponse.json();
        const sigTbody = document.getElementById('signals-tbody-terminal');
        if (sigTbody && sigData.signals && sigData.signals.length > 0) {
            sigTbody.innerHTML = '';
            sigData.signals.slice(0, 10).forEach(s => {
                const time = new Date(s.created_at).toLocaleTimeString();
                sigTbody.innerHTML += `
                    <tr>
                        <td>${time}</td>
                        <td><span class="symbol-badge">${s.symbol}</span></td>
                        <td>${s.trigger_price.toFixed(1)}</td>
                        <td><span style="color:var(--accent-cyan); font-weight:700;">${s.action.toUpperCase()}</span></td>
                    </tr>
                `;
            });
        }
        
        // Fetch Orders
        const ordResponse = await fetch('/api/orders');
        const ordData = await ordResponse.json();
        const ordTbody = document.getElementById('orders-tbody-terminal');
        if (ordTbody && ordData.orders && ordData.orders.length > 0) {
            ordTbody.innerHTML = '';
            ordData.orders.slice(0, 10).forEach(o => {
                let statusText = o.status.toUpperCase();
                let statColor = 'var(--text-secondary)';
                if (o.status === 'pending') {
                    statusText = 'PROCESSING';
                    statColor = 'var(--accent-amber)';
                } else if (o.status === 'executed' || o.status === 'submitted') {
                    statusText = 'COMPLETE';
                    statColor = 'var(--accent-emerald)';
                } else {
                    statusText = o.status.toUpperCase();
                    statColor = 'var(--accent-rose)';
                }

                const time = (o.status === 'pending') ? '__' : (o.executed_at ? window.formatTime(o.executed_at) : '--');
                const latency = (o.status === 'pending') ? '__' : (o.latency_ms ? `${o.latency_ms.toFixed(2)} ms` : '--');
                
                ordTbody.innerHTML += `
                    <tr>
                        <td>${time}</td>
                        <td><span class="symbol-badge">${o.symbol}</span></td>
                        <td>${o.quantity}@${o.price.toFixed(1)}</td>
                        <td style="color: var(--accent-cyan); font-weight: 600;">${latency}</td>
                        <td><span style="color:${statColor}; font-weight:700;">${statusText}</span></td>
                    </tr>
                `;
            });
        }
    } catch (err) {
        console.error("Failed to fetch secondary info: ", err);
    }
};

// Fetch Server Uptime
window.fetchUptime = async function() {
    try {
        const r = await fetch('/api/health');
        const d = await r.json();
        const uptimeEl = document.getElementById('stat-uptime');
        if (uptimeEl) {
            uptimeEl.textContent = d.uptime || 'unknown';
        }
    } catch (e) {
        console.error("Failed to fetch uptime: ", e);
    }
};

// Real-time log file viewer
window.fetchConsoleLogs = async function() {
    try {
        const response = await fetch('/api/logs');
        const data = await response.json();
        window.globalState.rawLogLines = data.logs || [];
        window.applyLogFilters();
    } catch (err) {
        console.error("Failed to load logs: ", err);
    }
};

// Set logs panel filter
window.setLogFilter = function(filter) {
    window.globalState.currentLogFilter = filter;
    document.querySelectorAll('.terminal-btn-filter').forEach(btn => {
        btn.classList.remove('active');
    });
    
    const index = { 'all': 0, 'debug': 1, 'info': 2, 'warning': 3, 'error': 4 }[filter];
    const targetBtn = document.querySelectorAll('.terminal-btn-filter')[index];
    if (targetBtn) {
        targetBtn.classList.add('active');
    }
    window.applyLogFilters();
};

// Apply filters (search and log level)
window.applyLogFilters = function() {
    const tbody = document.getElementById('terminal-body-el');
    if (!tbody) return;
    tbody.innerHTML = '';
    
    const searchVal = document.getElementById('log-search-input').value.toLowerCase();
    let filtered = window.globalState.rawLogLines;
    
    // Filter by level
    if (window.globalState.currentLogFilter !== 'all') {
        filtered = filtered.filter(line => {
            const lineLower = line.toLowerCase();
            return lineLower.includes(`"level": "${window.globalState.currentLogFilter}"`) || 
                   lineLower.includes(`"level": "${window.globalState.currentLogFilter === 'warning' ? 'warn' : window.globalState.currentLogFilter}"`);
        });
    }

    // Filter by search query
    if (searchVal) {
        filtered = filtered.filter(line => line.toLowerCase().includes(searchVal));
    }

    if (filtered.length === 0) {
        tbody.innerHTML = `<div class="terminal-line"><span class="terminal-msg" style="color:var(--text-muted)">No matching log entries found.</span></div>`;
        return;
    }

    filtered.forEach(line => {
        const div = document.createElement('div');
        div.className = 'terminal-line';
        
        try {
            const parsed = JSON.parse(line);
            const timestamp = parsed.timestamp ? new Date(parsed.timestamp).toLocaleTimeString() : '';
            const level = parsed.level || 'info';
            
            let meta = '';
            for (const [k, v] of Object.entries(parsed)) {
                if (['timestamp', 'level', 'event', 'logger'].includes(k)) continue;
                meta += ` <span style="color:var(--text-secondary)">${k}=</span><span style="color:var(--accent-cyan)">${JSON.stringify(v)}</span>`;
            }

            div.innerHTML = `
                <span class="terminal-time">[${timestamp}]</span>
                <span class="terminal-level level-${level.toLowerCase()}">${level}</span>
                <span class="terminal-msg"><strong>${parsed.event || ''}</strong>${meta}</span>
            `;
        } catch (e) {
            let levelClass = 'level-info';
            let levelText = 'INFO';
            if (line.toLowerCase().includes('error')) { levelClass = 'level-error'; levelText = 'ERROR'; }
            else if (line.toLowerCase().includes('warn')) { levelClass = 'level-warn'; levelText = 'WARN'; }
            else if (line.toLowerCase().includes('debug')) { levelClass = 'level-debug'; levelText = 'DEBUG'; }

            div.innerHTML = `
                <span class="terminal-level ${levelClass}">${levelText}</span>
                <span class="terminal-msg">${line}</span>
            `;
        }
        tbody.appendChild(div);
    });

    // Scroll to bottom
    tbody.scrollTop = tbody.scrollHeight;
};

// Refresh Browser Screen Frame screenshot
window.refreshBrowserScreenshot = async function() {
    const timestampEl = document.getElementById('screenshot-timestamp');
    if (timestampEl) timestampEl.textContent = 'LAST UPDATE: CAPTURING...';
    
    const img = document.getElementById('browser-screenshot-img');
    if (img) {
        img.src = '/api/screenshot?t=' + new Date().getTime(); // Cache breaker query parameter
        img.onload = () => {
            if (timestampEl) {
                const now = new Date();
                timestampEl.textContent = `LAST CAPTURE: ${now.toLocaleTimeString()}`;
            }
        };
    }
};

// Fetch active system warnings (clock drift, collateral checks, etc.)
window.fetchSystemWarnings = async function() {
    try {
        const response = await fetch('/api/system/warnings');
        const d = await response.json();
        const container = document.getElementById('alerts-container');
        if (container) {
            container.innerHTML = ''; // clear existing
            if (d.warnings && d.warnings.length > 0) {
                d.warnings.forEach(w => {
                    const alertHtml = `
                        <div class="glass-panel alert-banner-item" style="border-left: 4px solid var(--accent-amber); padding: 0.75rem 1rem; display: flex; justify-content: space-between; align-items: center; background: rgba(217, 119, 6, 0.1); margin-top: 0.5rem; width: 100%;">
                            <div style="display: flex; align-items: center; gap: 0.75rem;">
                                <span style="font-size: 1.25rem;">⚠️</span>
                                <div>
                                    <strong style="color: var(--text-primary);">${w.title}:</strong>
                                    <span style="color: var(--text-secondary); margin-left: 0.25rem;">${w.message}</span>
                                </div>
                            </div>
                            <button onclick="this.parentElement.remove()" style="background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 1.25rem; font-weight: bold; line-height: 1;">&times;</button>
                        </div>
                    `;
                    container.insertAdjacentHTML('beforeend', alertHtml);
                });
            }
        }
    } catch (err) {
        console.error("Failed to fetch system warnings: ", err);
    }
};

// Fetch available collateral and staging costs
window.fetchCollateralDetails = async function() {
    try {
        const response = await fetch('/api/collateral');
        const data = await response.json();
        
        const collateralEl = document.getElementById('stat-collateral');
        if (collateralEl) {
            collateralEl.textContent = data.collateral !== undefined ? `NPR ${data.collateral.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}` : '--';
        }
        
        const costEl = document.getElementById('stat-cost-label');
        if (costEl) {
            costEl.textContent = data.staging_cost !== undefined ? `Staging Cost: NPR ${data.staging_cost.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}` : 'Staging Cost: --';
        }
    } catch (err) {
        console.error("Failed to fetch collateral details: ", err);
    }
};
