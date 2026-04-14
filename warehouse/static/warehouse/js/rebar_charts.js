window.RebarCharts = {
    init: function () {
        var labels   = JSON.parse(document.getElementById('chart-labels').textContent || '[]');
        var planData = JSON.parse(document.getElementById('chart-plan').textContent   || '[]');
        var factData = JSON.parse(document.getElementById('chart-fact').textContent   || '[]');

        if (!labels.length) return;

        var ctx = document.getElementById('rebarChart');
        if (!ctx) return;

        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'План (т)',
                        data: planData,
                        backgroundColor: 'rgba(148,163,184,0.5)',
                        borderColor: 'rgba(148,163,184,1)',
                        borderWidth: 1,
                        borderRadius: 4,
                    },
                    {
                        label: 'Факт (т)',
                        data: factData,
                        backgroundColor: 'rgba(100,116,139,0.85)',
                        borderColor: 'rgba(71,85,105,1)',
                        borderWidth: 1,
                        borderRadius: 4,
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'top', labels: { boxWidth: 12, font: { size: 12 } } },
                    tooltip: { mode: 'index', intersect: false }
                },
                scales: {
                    x: { ticks: { maxRotation: 35, font: { size: 11 } }, grid: { display: false } },
                    y: { beginAtZero: true, ticks: { font: { size: 11 } } }
                }
            }
        });
    }
};
