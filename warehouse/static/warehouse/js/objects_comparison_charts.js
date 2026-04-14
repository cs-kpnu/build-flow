window.ObjectsComparisonCharts = {
    init: function () {
        var data = JSON.parse(document.getElementById('comparison-data').textContent || '[]');

        if (!data.length) return;

        var ctx = document.getElementById('comparisonChart');
        if (!ctx) return;

        var labels     = data.map(function(r) { return r.name; });
        var values     = data.map(function(r) { return r.value || r.total_value || 0; });

        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Вартість залишків (₴)',
                    data: values,
                    backgroundColor: [
                        'rgba(37,99,235,0.8)',
                        'rgba(16,185,129,0.8)',
                        'rgba(245,158,11,0.8)',
                        'rgba(239,68,68,0.8)',
                        'rgba(139,92,246,0.8)',
                    ],
                    borderWidth: 0,
                    borderRadius: 6,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: function(ctx) {
                                return ' ' + Number(ctx.raw).toLocaleString('uk-UA') + ' ₴';
                            }
                        }
                    }
                },
                scales: {
                    x: { ticks: { font: { size: 12 } }, grid: { display: false } },
                    y: { beginAtZero: true, ticks: { font: { size: 11 } } }
                }
            }
        });
    }
};
