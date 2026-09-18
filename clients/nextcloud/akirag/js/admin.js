(function () {
    'use strict';

    function init() {
        var root = document.getElementById('akirag-admin');
        if (!root) {
            return;
        }
        var save = document.getElementById('akirag-save');
        var url = document.getElementById('akirag-middleware-url');
        var key = document.getElementById('akirag-api-key');
        var status = document.getElementById('akirag-admin-status');

        save.addEventListener('click', function () {
            save.disabled = true;
            status.textContent = 'Speichere …';

            fetch(OC.generateUrl('/apps/akirag/admin/config'), {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    'requesttoken': OC.requestToken
                },
                body: JSON.stringify({
                    middlewareUrl: url.value.trim(),
                    apiKey: key.value.trim()
                })
            }).then(function (response) {
                return response.json().catch(function () { return {}; }).then(function (data) {
                    if (!response.ok) {
                        throw new Error(data.error || ('HTTP ' + response.status));
                    }
                    return data;
                });
            }).then(function () {
                key.value = '';
                key.placeholder = 'API-Key ist gespeichert – leer lassen zum Beibehalten';
                status.textContent = 'Gespeichert.';
                save.disabled = false;
            }).catch(function (error) {
                status.textContent = 'Fehler: ' + error.message;
                save.disabled = false;
            });
        });
    }

    document.addEventListener('DOMContentLoaded', init);
}());
