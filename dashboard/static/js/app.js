// Global Application State
window.globalState = {
    soundEnabled: true,
    activeTab: 'tab-terminal',
    watchlistData: [],
    rawLogLines: [],
    currentLogFilter: 'all',
    latencyDataBuffer: [],
    tickLabelsBuffer: [],
    ticksCounterData: {}
};

// Audio Context for programmatically generated Synthesizer alerts
const audioCtx = new (window.AudioContext || window.webkitAudioContext)();

window.playAlert = function(type) {
    if (!window.globalState.soundEnabled) return;
    try {
        if (audioCtx.state === 'suspended') {
            audioCtx.resume();
        }
        
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        
        if (type === 'success') {
            // Sweet double high chime (cash register type)
            osc.type = 'triangle';
            osc.frequency.setValueAtTime(880, audioCtx.currentTime); // A5
            gain.gain.setValueAtTime(0.15, audioCtx.currentTime);
            osc.start();
            osc.stop(audioCtx.currentTime + 0.1);
            
            const osc2 = audioCtx.createOscillator();
            const gain2 = audioCtx.createGain();
            osc2.connect(gain2);
            gain2.connect(audioCtx.destination);
            osc2.type = 'triangle';
            osc2.frequency.setValueAtTime(1320, audioCtx.currentTime + 0.08); // E6
            gain2.gain.setValueAtTime(0.15, audioCtx.currentTime + 0.08);
            osc2.start(audioCtx.currentTime + 0.08);
            osc2.stop(audioCtx.currentTime + 0.25);
        } 
        else if (type === 'error') {
            // Double low warning buzz
            osc.type = 'sawtooth';
            osc.frequency.setValueAtTime(130, audioCtx.currentTime); // C3
            gain.gain.setValueAtTime(0.2, audioCtx.currentTime);
            osc.start();
            gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.3);
            osc.stop(audioCtx.currentTime + 0.35);
        }
        else if (type === 'warning') {
            // Medium sweep alarm
            osc.type = 'sine';
            osc.frequency.setValueAtTime(440, audioCtx.currentTime);
            osc.frequency.linearRampToValueAtTime(880, audioCtx.currentTime + 0.3);
            gain.gain.setValueAtTime(0.15, audioCtx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.3);
            osc.start();
            osc.stop(audioCtx.currentTime + 0.35);
        }
        else if (type === 'connect') {
            // High-pitched pleasant bleep
            osc.type = 'sine';
            osc.frequency.setValueAtTime(1000, audioCtx.currentTime);
            gain.gain.setValueAtTime(0.1, audioCtx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.15);
            osc.start();
            osc.stop(audioCtx.currentTime + 0.18);
        }
    } catch (e) {
        console.error("Audio generation failed: ", e);
    }
};

// Toggle Sound Option
window.toggleSound = function() {
    window.globalState.soundEnabled = !window.globalState.soundEnabled;
    const btn = document.getElementById('sound-btn');
    const mobileBtn = document.getElementById('mobile-sound-btn');
    
    [btn, mobileBtn].forEach(el => {
        if (el) {
            if (window.globalState.soundEnabled) {
                el.classList.add('sound-on');
                el.textContent = '🔊';
            } else {
                el.classList.remove('sound-on');
                el.textContent = '🔇';
            }
        }
    });
};

// Toast Notifications
window.showToast = function(message, type = "info") {
    const container = document.getElementById('toast-container');
    if (!container) return;
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    let typeIcon = "ℹ️";
    if (type === 'success') typeIcon = "✅";
    if (type === 'error') typeIcon = "❌";
    if (type === 'warn') typeIcon = "⚠️";
    
    toast.innerHTML = `
        <div style="display:flex; align-items:center; gap:0.55rem;">
            <span>${typeIcon}</span>
            <span>${message}</span>
        </div>
        <span style="cursor:pointer; opacity:0.6; font-size:0.75rem; margin-left:1.5rem;" onclick="this.parentElement.remove()">✕</span>
    `;
    container.appendChild(toast);
    
    // Auto close after 4s
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.4s ease';
        setTimeout(() => toast.remove(), 400);
    }, 4000);
};

// High precision formatting for ISO timestamps
window.formatTime = function(isoString) {
    if (!isoString) return '--';
    const date = new Date(isoString);
    const pad = (n) => String(n).padStart(2, '0');
    const padMs = (n) => String(n).padStart(3, '0');
    return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${padMs(date.getMilliseconds())}`;
};

// Tab Switching Navigation
window.switchTab = function(tabId) {
    window.globalState.activeTab = tabId;
    
    // Update desktop sidebar buttons
    document.querySelectorAll('.sidebar-menu-btn').forEach(btn => {
        if (btn.getAttribute('onclick').includes(tabId)) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
    
    // Update content pane visibility
    document.querySelectorAll('.tab-content').forEach(content => {
        if (content.id === tabId) {
            content.classList.add('active');
        } else {
            content.classList.remove('active');
        }
    });
    
    // Close mobile menu on switch
    window.closeMobileSidebar();
    
    // Fetch logs immediately if log tab is open
    if (tabId === 'tab-logs') {
        window.fetchConsoleLogs();
    }
};

// Mobile Sidebar Utilities
window.toggleMobileSidebar = function() {
    const sidebar = document.getElementById('sidebar-menu-el');
    const backdrop = document.getElementById('sidebar-backdrop-el');
    if (sidebar && backdrop) {
        sidebar.classList.toggle('open');
        backdrop.classList.toggle('open');
    }
};

window.closeMobileSidebar = function() {
    const sidebar = document.getElementById('sidebar-menu-el');
    const backdrop = document.getElementById('sidebar-backdrop-el');
    if (sidebar && backdrop) {
        sidebar.classList.remove('open');
        backdrop.classList.remove('open');
    }
};

// Update header/sidebar system counters
window.updateSystemStats = function(data) {
    if (data.metrics) {
        const e2e = data.metrics.end_to_end_latency && data.metrics.end_to_end_latency.count > 0 ? data.metrics.end_to_end_latency : data.metrics.detection_latency;
        if (e2e) {
            const p95Val = e2e.p95 || 0;
            const latencyEl = document.getElementById('stat-latency');
            if (latencyEl) {
                latencyEl.textContent = `${p95Val.toFixed(1)} ms`;
                
                const label = latencyEl.nextElementSibling;
                if (label) {
                    if (data.metrics.end_to_end_latency && data.metrics.end_to_end_latency.count > 0) {
                        label.textContent = "EventBus E2E Loop";
                    } else {
                        label.textContent = "Bot Pipeline Latency";
                    }
                }
                
                // Color code latency card based on response speed
                const card = latencyEl.parentElement;
                if (card) {
                    card.className = 'glass-panel stat-card'; // clear previous
                    if (p95Val <= 5.0) card.classList.add('success');
                    else if (p95Val <= 15.0) card.classList.add('amber');
                    else card.classList.add('danger');
                }
            }
        }
    }
    
    if (data.counters) {
        const executed = data.counters.orders_executed || 0;
        const ordersEl = document.getElementById('stat-orders');
        if (ordersEl) {
            const oldVal = parseInt(ordersEl.textContent) || 0;
            ordersEl.textContent = executed;
            // Play audio cue if orders executed count increases
            if (executed > oldVal && oldVal > 0) {
                window.playAlert('success');
                window.showToast("Order Executed successfully on TMS!", "success");
            }
        }
    }
};

// Websocket connection initialization
function initWebSocket() {
    const wsProtocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${wsProtocol}//${location.host}/ws`);
    
    ws.onopen = () => {
        const statusEl = document.getElementById('connection-status');
        const mobileStatusEl = document.getElementById('mobile-connection-status');
        [statusEl, mobileStatusEl].forEach(el => {
            if (el) {
                el.innerHTML = '<span class="status-dot"></span> Websocket Connected';
                el.className = 'badge badge-success';
            }
        });
        window.showToast("Trading Terminal connected to WebSocket.", "success");
        window.playAlert('connect');
    };
    
    ws.onclose = () => {
        const statusEl = document.getElementById('connection-status');
        const mobileStatusEl = document.getElementById('mobile-connection-status');
        [statusEl, mobileStatusEl].forEach(el => {
            if (el) {
                el.innerHTML = '<span class="status-dot"></span> Disconnected';
                el.className = 'badge badge-danger';
            }
        });
        window.showToast("WebSocket channel disconnected. Reconnecting...", "error");
        window.playAlert('error');
        setTimeout(initWebSocket, 2000); // Autoreconnect
    };
    
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'update') {
            if (typeof window.updateLiveFeed === 'function') window.updateLiveFeed(data);
            window.updateSystemStats(data);
            if (typeof window.updateChartsData === 'function') window.updateChartsData(data);
        } else if (data.type === 'event') {
            if (typeof window.updateLiveFeed === 'function') window.updateLiveFeed(data);
            window.updateSystemStats(data);
            if (typeof window.updateChartsData === 'function') window.updateChartsData(data);
            
            const ev = data.event;
            if (ev && ev.type) {
                if (ev.type === 'market_data.circuit_hit') {
                    window.showToast(`⚡ CIRCUIT LIMIT HIT: ${ev.data.symbol} is at upper limit!`, "warn");
                    window.playAlert('warning');
                } else if (ev.type === 'strategy.signal') {
                    window.showToast(`🎯 Signal Generated: ${ev.data.symbol} trigger price reached!`, "success");
                    window.playAlert('success');
                    if (typeof window.fetchSecondaryInfo === 'function') window.fetchSecondaryInfo();
                } else if (ev.type === 'order.submitted') {
                    window.showToast(`📤 Order Staged: Submitting ${ev.data.symbol} (${ev.data.quantity} shares)`, "info");
                    window.playAlert('connect');
                    if (typeof window.fetchSecondaryInfo === 'function') window.fetchSecondaryInfo();
                    if (typeof window.fetchSystemHealth === 'function') window.fetchSystemHealth();
                } else if (ev.type === 'order.executed') {
                    window.showToast(`✅ Order Executed: ${ev.data.symbol} ${ev.data.quantity} @ ${ev.data.price}`, "success");
                    window.playAlert('success');
                    if (typeof window.fetchSecondaryInfo === 'function') window.fetchSecondaryInfo();
                    if (typeof window.fetchSystemHealth === 'function') window.fetchSystemHealth();
                } else if (ev.type === 'order.failed') {
                    window.showToast(`❌ Order Failed: ${ev.data.symbol} - ${ev.data.error || 'Unknown error'}`, "error");
                    window.playAlert('error');
                    if (typeof window.fetchSecondaryInfo === 'function') window.fetchSecondaryInfo();
                    if (typeof window.fetchSystemHealth === 'function') window.fetchSystemHealth();
                } else if (ev.type === 'risk.kill_switch') {
                    window.showToast(`🚨 CRITICAL: Kill Switch Activated! ${ev.data.reason || ''}`, "error");
                    window.playAlert('error');
                    if (typeof window.fetchSystemHealth === 'function') window.fetchSystemHealth();
                } else if (ev.type === 'system.warning') {
                    window.showToast(`⚠️ ${ev.data.title || 'Warning'}: ${ev.data.message}`, "warn");
                    window.playAlert('warning');
                    const container = document.getElementById('alerts-container');
                    if (container) {
                        const alertHtml = `
                            <div class="glass-panel alert-banner-item" style="border-left: 4px solid var(--accent-amber); padding: 0.75rem 1rem; display: flex; justify-content: space-between; align-items: center; background: rgba(217, 119, 6, 0.1); margin-top: 0.5rem;">
                                <div style="display: flex; align-items: center; gap: 0.75rem;">
                                    <span style="font-size: 1.25rem;">⚠️</span>
                                    <div>
                                        <strong style="color: var(--text-primary);">${ev.data.title}:</strong>
                                        <span style="color: var(--text-secondary); margin-left: 0.25rem;">${ev.data.message}</span>
                                    </div>
                                </div>
                                <button onclick="this.parentElement.remove()" style="background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 1.25rem; font-weight: bold; line-height: 1;">&times;</button>
                            </div>
                        `;
                        container.insertAdjacentHTML('beforeend', alertHtml);
                    }
                }
            }
        }
    };
}

// App startup bootstrap
document.addEventListener('DOMContentLoaded', () => {
    initWebSocket();
    
    if (typeof window.loadWatchlist === 'function') window.loadWatchlist();
    if (typeof window.fetchSystemHealth === 'function') window.fetchSystemHealth();
    if (typeof window.fetchSystemWarnings === 'function') window.fetchSystemWarnings();
    if (typeof window.fetchSecondaryInfo === 'function') window.fetchSecondaryInfo();
    if (typeof window.fetchUptime === 'function') window.fetchUptime();
    if (typeof window.fetchCollateralDetails === 'function') window.fetchCollateralDetails();
    
    // Auto-update secondary info and health on timer loops
    setInterval(() => {
        if (typeof window.fetchSystemHealth === 'function') window.fetchSystemHealth();
    }, 3000);
    
    setInterval(() => {
        if (typeof window.fetchSystemWarnings === 'function') window.fetchSystemWarnings();
    }, 5000);
    
    setInterval(() => {
        if (typeof window.fetchSecondaryInfo === 'function') window.fetchSecondaryInfo();
    }, 2500);
    
    setInterval(() => {
        if (typeof window.fetchUptime === 'function') window.fetchUptime();
    }, 5000);
    
    setInterval(() => {
        if (typeof window.fetchCollateralDetails === 'function') window.fetchCollateralDetails();
    }, 3000);
    
    // Logs panel streamer loop (only when active logs tab is open)
    setInterval(() => {
        if (window.globalState.activeTab === 'tab-logs') {
            if (typeof window.fetchConsoleLogs === 'function') window.fetchConsoleLogs();
        }
    }, 1500);
});
