window.FinancialCharts = {
    init: function () {
        // Графік постачальників (doughnut)
        var supLabels = JSON.parse(document.getElementById('sup-labels').textContent || '[]');
        var supData   = JSON.parse(document.getElementById('sup-data').textContent   || '[]');

        if (supLabels.length) {
            var ctxSup = document.getElementById('suppliersChart');
            if (ctxSup) {
                new Chart(ctxSup, {
                    type: 'doughnut',
                    data: {
                        labels: supLabels,
                        datasets: [{
                            data: supData,
                            backgroundColor: [
                                'rgba(37,99,235,0.8)',
                                'rgba(16,185,129,0.8)',
                                'rgba(245,158,11,0.8)',
                                'rgba(239,68,68,0.8)',
                                'rgba(139,92,246,0.8)',
                                'rgba(20,184,166,0.8)',
                            ],
                            borderWidth: 2,
                            borderColor: '#fff',
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { position: 'right', labels: { font: { size: 11 }, boxWidth: 12 } },
                            tooltip: {
                                callbacks: {
                                    label: function(ctx) {
                                        return ' ' + ctx.label + ': ' + Number(ctx.raw).toLocaleString('uk-UA') + ' ₴';
                                    }
                                }
                            }
                        }
                    }
                });
            }
        }

        // Графік тренду витрат (line)
        var dateLabels = JSON.parse(document.getElementById('date-labels').textContent || '[]');
        var dateValues = JSON.parse(document.getElementById('date-values').textContent || '[]');

        if (dateLabels.length) {
            var ctxTrend = document.getElementById('trendChart');
            if (ctxTrend) {
                new Chart(ctxTrend, {
                    type: 'line',
                    data: {
                        labels: dateLabels,
                        datasets: [{
                            label: 'Витрати (₴)',
                            data: dateValues,
                            borderColor: 'rgba(37,99,235,1)',
                            backgroundColor: 'rgba(37,99,235,0.1)',
                            borderWidth: 2,
                            pointRadius: 4,
                            pointBackgroundColor: 'rgba(37,99,235,1)',
                            fill: true,
                            tension: 0.4,
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { display: false },
                            tooltip: { mode: 'index', intersect: false }
                        },
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
