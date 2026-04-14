// transaction_form.js — Handles transaction type toggle and stage loading via AJAX
(function () {
    document.addEventListener('DOMContentLoaded', function () {
        var form = document.getElementById('transactionForm');
        if (!form) return;

        var constructionDetails = document.getElementById('construction-details');
        var stageSelect = document.getElementById('id_stage');
        var warehouseSelect = form.querySelector('[name="warehouse"]');
        var stagesUrl = form.dataset.stagesUrl;

        // Show/hide construction details block based on transaction type
        function updateTypeUI() {
            var selected = form.querySelector('[name="transaction_type"]:checked');
            var type = selected ? selected.value : 'OUT';
            if (constructionDetails) {
                constructionDetails.style.display = (type === 'OUT') ? 'block' : 'none';
            }
        }

        // Load stages for selected warehouse
        function loadStages() {
            if (!stageSelect || !stagesUrl || !warehouseSelect) return;
            var warehouseId = warehouseSelect.value;
            if (!warehouseId) return;

            fetch(stagesUrl + '?warehouse=' + warehouseId, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            })
            .then(function (r) { return r.json(); })
            .then(function (stages) {
                stageSelect.innerHTML = '<option value="">---------</option>';
                stages.forEach(function (s) {
                    var opt = document.createElement('option');
                    opt.value = s.id;
                    opt.textContent = s.name;
                    stageSelect.appendChild(opt);
                });
            })
            .catch(function () {});
        }

        // Bind events
        form.querySelectorAll('[name="transaction_type"]').forEach(function (radio) {
            radio.addEventListener('change', updateTypeUI);
        });

        if (warehouseSelect) {
            warehouseSelect.addEventListener('change', loadStages);
        }

        // Init on load
        updateTypeUI();
        loadStages();
    });
})();
