// confirm_receipt.js — Camera photo preview and reject toggle for receipt confirmation
window.ConfirmReceipt = {
    init: function () {
        var cameraInput = document.getElementById('cameraInput');
        var cameraLabel = document.getElementById('cameraLabel');
        var cameraText  = document.getElementById('cameraText');
        var previewContainer = document.getElementById('previewContainer');
        var previewImg  = document.getElementById('previewImg');

        // Photo preview
        if (cameraInput) {
            cameraInput.addEventListener('change', function () {
                var file = cameraInput.files[0];
                if (!file) return;

                var reader = new FileReader();
                reader.onload = function (e) {
                    if (previewImg) previewImg.src = e.target.result;
                    if (previewContainer) previewContainer.style.display = 'block';
                    if (cameraLabel) cameraLabel.classList.add('active');
                    if (cameraText) cameraText.textContent = file.name;
                };
                reader.readAsDataURL(file);
            });
        }

        // Reject toggle
        var rejectToggle   = document.getElementById('actReject');
        var blockReject    = document.getElementById('block-reject');
        var submitBtn      = document.getElementById('mainSubmitBtn');

        if (rejectToggle) {
            rejectToggle.addEventListener('change', function () {
                var isReject = rejectToggle.checked;
                if (blockReject) blockReject.style.display = isReject ? 'block' : 'none';
                if (submitBtn) {
                    if (isReject) {
                        submitBtn.classList.replace('btn-success', 'btn-danger');
                        submitBtn.innerHTML = '<i class="bi bi-x-circle me-2"></i> ЗАФІКСУВАТИ ПОВЕРНЕННЯ';
                    } else {
                        submitBtn.classList.replace('btn-danger', 'btn-success');
                        submitBtn.innerHTML = '<i class="bi bi-box-seam me-2"></i> ОПРИБУТКУВАТИ';
                    }
                }
            });
        }
    }
};
