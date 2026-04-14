// create_order.js — Django formset add/remove rows + photo dropzone
(function () {
    document.addEventListener('DOMContentLoaded', function () {

        // === FORMSET MANAGEMENT ===
        var container  = document.getElementById('formset-container');
        var addBtn     = document.getElementById('add-item-btn');
        var tmpl       = document.getElementById('empty-form');
        var totalInput = document.querySelector('[name$="-TOTAL_FORMS"]');

        if (addBtn && tmpl && container && totalInput) {
            addBtn.addEventListener('click', function () {
                var total = parseInt(totalInput.value, 10);
                var clone = tmpl.content.cloneNode(true);

                // Replace __prefix__ with current index
                clone.querySelectorAll('[name],[id],[for]').forEach(function (el) {
                    ['name','id','for'].forEach(function (attr) {
                        if (el.getAttribute(attr)) {
                            el.setAttribute(attr, el.getAttribute(attr).replace(/__prefix__/g, total));
                        }
                    });
                });

                container.appendChild(clone);
                totalInput.value = total + 1;

                // Init TomSelect on new selects if available
                container.querySelectorAll('.tom-select:not(.tomselected)').forEach(function (sel) {
                    if (window.TomSelect) new TomSelect(sel, { maxOptions: 300 });
                });
            });

            // Remove row
            container.addEventListener('click', function (e) {
                var btn = e.target.closest('[data-action="remove-row"]');
                if (!btn) return;
                var row = btn.closest('.item-row');
                if (!row) return;

                // Mark DELETE checkbox if present
                var delCb = row.querySelector('[name$="-DELETE"]');
                if (delCb) {
                    delCb.checked = true;
                    row.style.opacity = '0.3';
                    row.style.pointerEvents = 'none';
                } else {
                    row.remove();
                    totalInput.value = parseInt(totalInput.value, 10) - 1;
                }
            });
        }

        // === PHOTO DROPZONE ===
        var dropzone  = document.getElementById('uploadDropzone');
        var fileInput = document.getElementById('id_request_photo');
        var preview   = document.getElementById('previewContainer');
        var imgPrev   = document.getElementById('imgPreview');
        var fileNameEl = document.getElementById('fileName');
        var fileSizeEl = document.getElementById('fileSize');
        var removeBtn  = document.getElementById('removeFileBtn');
        var dropContent = document.getElementById('dropzoneContent');
        var errEl       = document.getElementById('uploadError');

        function showPreview(file) {
            if (!file) return;
            if (file.size > 10 * 1024 * 1024) {
                if (errEl) errEl.textContent = 'Файл занадто великий (макс. 10 MB)';
                return;
            }
            if (errEl) errEl.textContent = '';
            var reader = new FileReader();
            reader.onload = function (e) {
                if (imgPrev)   imgPrev.src = e.target.result;
                if (fileNameEl) fileNameEl.textContent = file.name;
                if (fileSizeEl) fileSizeEl.textContent = (file.size / 1024).toFixed(1) + ' KB';
                if (dropContent) dropContent.style.display = 'none';
                if (preview) preview.style.display = 'flex';
            };
            reader.readAsDataURL(file);
        }

        if (fileInput) {
            fileInput.addEventListener('change', function () {
                showPreview(fileInput.files[0]);
            });
        }

        if (dropzone && fileInput) {
            dropzone.addEventListener('dragover', function (e) {
                e.preventDefault();
                dropzone.classList.add('drag-over');
            });
            dropzone.addEventListener('dragleave', function () {
                dropzone.classList.remove('drag-over');
            });
            dropzone.addEventListener('drop', function (e) {
                e.preventDefault();
                dropzone.classList.remove('drag-over');
                var files = e.dataTransfer.files;
                if (files.length) {
                    var dt = new DataTransfer();
                    dt.items.add(files[0]);
                    fileInput.files = dt.files;
                    showPreview(files[0]);
                }
            });
        }

        if (removeBtn && fileInput) {
            removeBtn.addEventListener('click', function () {
                fileInput.value = '';
                if (preview) preview.style.display = 'none';
                if (dropContent) dropContent.style.display = 'block';
                if (imgPrev) imgPrev.src = '';
            });
        }
    });
})();
