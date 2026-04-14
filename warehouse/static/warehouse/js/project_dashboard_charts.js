window.ProjectDashboardCharts = {
    init: function () {
        var stages = JSON.parse(document.getElementById('concrete-stages-data').textContent || '[]');

        if (!stages.length) return;

        var labels   = stages.map(function(s) { return s.name; });
        var planData = stages.map(function(s) { return s.plan; });
        var factData = stages.map(function(s) { return s.fact; });

        var ctx = document.getElementById('concreteProgressChart');
        if (!ctx) return;

        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'План (м³)',
                        data: planData,
                        backgroundColor: 'rgba(148,163,184,0.5)',
                        borderColor: 'rgba(148,163,184,1)',
                        borderWidth: 1,
                        borderRadius: 4,
                    },
                    {
                        label: 'Факт (м³)',
                        data: factData,
                        backgroundColor: 'rgba(37,99,235,0.85)',
                        borderColor: 'rgba(37,99,235,1)',
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
                    x: { ticks: { maxRotation: 30, font: { size: 11 } }, grid: { display: false } },
                    y: { beginAtZero: true, ticks: { font: { size: 11 } } }
                }
            }
        });
    }
};
