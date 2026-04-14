// stock_ajax.js — Shows current stock balance for selected material + warehouse
(function () {
    document.addEventListener('DOMContentLoaded', function () {
        var form = document.querySelector('[data-stock-validate]');
        if (!form) return;

        var hintTarget = document.querySelector(form.dataset.hintTarget || '#stock-hint');
        var materialSelect = form.querySelector('[name="material"]');
        var warehouseSelect = form.querySelector('[name="warehouse"]') ||
                              form.querySelector('[name="source_warehouse"]');

        if (!materialSelect || !hintTarget) return;

        function fetchStock() {
            var materialId = materialSelect.value;
            var warehouseId = warehouseSelect ? warehouseSelect.value : '';

            if (!materialId) {
                hintTarget.style.display = 'none';
                return;
            }

            var url = '/warehouse/ajax/warehouse-stock/?material=' + materialId;
            if (warehouseId) url += '&warehouse=' + warehouseId;

            fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.stock !== undefined) {
                        hintTarget.innerHTML =
                            '<i class="bi bi-box-seam me-1"></i> Залишок: <strong>' +
                            Number(data.stock).toLocaleString('uk-UA') + ' ' + (data.unit || '') +
                            '</strong>';
                        hintTarget.style.display = 'block';
                    } else {
                        hintTarget.style.display = 'none';
                    }
                })
                .catch(function () { hintTarget.style.display = 'none'; });
        }

        materialSelect.addEventListener('change', fetchStock);
        if (warehouseSelect) warehouseSelect.addEventListener('change', fetchStock);
    });
})();
