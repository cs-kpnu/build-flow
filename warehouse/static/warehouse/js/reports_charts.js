window.ReportsCharts = {
    init: function () {
        // Графік по складах (doughnut)
        var whLabels = JSON.parse(document.getElementById('wh-labels').textContent || '[]');
        var whData   = JSON.parse(document.getElementById('wh-data').textContent   || '[]');

        if (whLabels.length) {
            var ctxWh = document.getElementById('whChart');
            if (ctxWh) {
                new Chart(ctxWh, {
                    type: 'doughnut',
                    data: {
                        labels: whLabels,
                        datasets: [{
                            data: whData,
                            backgroundColor: [
                                'rgba(37,99,235,0.8)',
                                'rgba(16,185,129,0.8)',
                                'rgba(245,158,11,0.8)',
                                'rgba(239,68,68,0.8)',
                                'rgba(139,92,246,0.8)',
                            ],
                            borderWidth: 2,
                            borderColor: '#fff',
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { position: 'right', labels: { font: { size: 11 }, boxWidth: 12 } }
                        }
                    }
                });
            }
        }

        // Графік тренду по місяцях (line)
        var monthLabels = JSON.parse(document.getElementById('month-labels').textContent || '[]');
        var monthData   = JSON.parse(document.getElementById('month-data').textContent   || '[]');

        if (monthLabels.length) {
            var ctxTrend = document.getElementById('trendChart');
            if (ctxTrend) {
                new Chart(ctxTrend, {
                    type: 'line',
                    data: {
                        labels: monthLabels,
                        datasets: [{
                            label: 'Транзакції',
                            data: monthData,
                            borderColor: 'rgba(37,99,235,1)',
                            backgroundColor: 'rgba(37,99,235,0.1)',
                            borderWidth: 2,
                            pointRadius: 4,
                            fill: true,
                            tension: 0.4,
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: {
                            x: { ticks: { font: { size: 11 } }, grid: { display: false } },
                            y: { beginAtZero: true, ticks: { font: { size: 11 } } }
                        }
                    }
                });
            }
        }
    }
};
