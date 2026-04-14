window.TransferCharts = {
    init: function () {
        // Chart 1: Top materials by transfer count
        var matLabels = JSON.parse(document.getElementById('mat-labels').textContent || '[]');
        var matData   = JSON.parse(document.getElementById('mat-data').textContent   || '[]');

        if (matLabels.length) {
            var ctxMat = document.getElementById('matChart');
            if (ctxMat) {
                new Chart(ctxMat, {
                    type: 'bar',
                    data: {
                        labels: matLabels,
                        datasets: [{
                            label: 'Рейсів',
                            data: matData,
                            backgroundColor: 'rgba(6,182,212,0.8)',
                            borderRadius: 6,
                            borderWidth: 0,
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: {
                            x: { ticks: { font: { size: 11 } }, grid: { display: false } },
                            y: { beginAtZero: true, ticks: { font: { size: 11 }, stepSize: 1 } }
                        }
                    }
                });
            }
        }

        // Chart 2: Warehouse activity (source warehouses)
        var routeLabels = JSON.parse(document.getElementById('route-labels').textContent || '[]');
        var routeData   = JSON.parse(document.getElementById('route-data').textContent   || '[]');

        if (routeLabels.length) {
            var ctxRoute = document.getElementById('routeChart');
            if (ctxRoute) {
                new Chart(ctxRoute, {
                    type: 'bar',
                    data: {
                        labels: routeLabels,
                        datasets: [{
                            label: 'Відправлень',
                            data: routeData,
                            backgroundColor: 'rgba(37,99,235,0.8)',
                            borderRadius: 6,
                            borderWidth: 0,
                        }]
                    },
                    options: {
                        indexAxis: 'y',
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: {
                            x: { beginAtZero: true, ticks: { font: { size: 11 }, stepSize: 1 } },
                            y: { ticks: { font: { size: 11 } }, grid: { display: false } }
                        }
                    }
                });
            }
        }
    }
};
