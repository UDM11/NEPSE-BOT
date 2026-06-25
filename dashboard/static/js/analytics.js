// Keep local charts data buffer and update them
window.updateChartsData = function(d) {
    if (d.metrics) {
        const e2e = d.metrics.end_to_end_latency && d.metrics.end_to_end_latency.count > 0 ? d.metrics.end_to_end_latency : d.metrics.detection_latency;
        if (e2e) {
            const timeLabel = new Date(d.timestamp).toLocaleTimeString();
            
            window.globalState.latencyDataBuffer.push(e2e.p95 || 0.0);
            window.globalState.tickLabelsBuffer.push(timeLabel);

            if (window.globalState.latencyDataBuffer.length > 25) {
                window.globalState.latencyDataBuffer.shift();
                window.globalState.tickLabelsBuffer.shift();
            }

            if (window.globalState.activeTab === 'tab-analytics') {
                window.renderCharts();
            }
        }
    }

    if (d.watchlist) {
        d.watchlist.forEach(s => {
            if (s.volume > 0) {
                window.globalState.ticksCounterData[s.symbol] = s.volume;
            }
        });
    }
};

// Render Chart.js analytics graphs
window.renderCharts = function() {
    const latencyChartCanvas = document.getElementById('latencyChart');
    const volumeChartCanvas = document.getElementById('volumeChart');
    if (!latencyChartCanvas || !volumeChartCanvas) return;

    if (!window.globalState.latencyChartInstance) {
        const ctx = latencyChartCanvas.getContext('2d');
        window.globalState.latencyChartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: window.globalState.tickLabelsBuffer,
                datasets: [{
                    label: 'E2E Latency (p95 ms)',
                    data: window.globalState.latencyDataBuffer,
                    borderColor: '#00f0ff',
                    backgroundColor: 'rgba(0, 240, 255, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } },
                    x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } }
                },
                plugins: {
                    legend: { display: false }
                }
            }
        });
    } else {
        window.globalState.latencyChartInstance.data.labels = window.globalState.tickLabelsBuffer;
        window.globalState.latencyChartInstance.data.datasets[0].data = window.globalState.latencyDataBuffer;
        window.globalState.latencyChartInstance.update('none');
    }

    // Show all watchlist symbols on the chart even if volume is 0
    const symbols = window.globalState.watchlistData.map(item => item.symbol);
    const volumes = symbols.map(sym => window.globalState.ticksCounterData[sym] || 0);

    if (!window.globalState.volumeChartInstance) {
        const ctxVol = volumeChartCanvas.getContext('2d');
        window.globalState.volumeChartInstance = new Chart(ctxVol, {
            type: 'bar',
            data: {
                labels: symbols,
                datasets: [{
                    label: 'Traded Volume',
                    data: volumes,
                    backgroundColor: 'rgba(99, 102, 241, 0.65)',
                    borderColor: '#6366f1',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } },
                    x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } }
                },
                plugins: {
                    legend: { display: false }
                }
            }
        });
    } else {
        window.globalState.volumeChartInstance.data.labels = symbols;
        window.globalState.volumeChartInstance.data.datasets[0].data = volumes;
        window.globalState.volumeChartInstance.update('none');
    }
};
