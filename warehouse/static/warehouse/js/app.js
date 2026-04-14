// BudSklad ERP — Global App JS

// Sidebar toggle (mobile)
function toggleSidebar() {
    var sidebar = document.getElementById('sidebar');
    if (sidebar) sidebar.classList.toggle('show');
}

// Close sidebar on outside click (mobile)
document.addEventListener('click', function(e) {
    var sidebar = document.getElementById('sidebar');
    if (!sidebar) return;
    var btn = document.querySelector('[onclick="toggleSidebar()"]');
    if (sidebar.classList.contains('show') && !sidebar.contains(e.target) && (!btn || !btn.contains(e.target))) {
        sidebar.classList.remove('show');
    }
});

// Auto-dismiss alerts after 4s
document.addEventListener('DOMContentLoaded', function () {
    setTimeout(function () {
        document.querySelectorAll('.alert-dismissible.auto-dismiss, .messages .alert').forEach(function (el) {
            var bsAlert = bootstrap.Alert.getOrCreateInstance(el);
            if (bsAlert) bsAlert.close();
        });
    }, 4000);
});
