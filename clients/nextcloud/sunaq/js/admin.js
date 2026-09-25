(function () {
    'use strict';

    function init() {
        var root = document.getElementById('sunaq-admin');
        if (!root) {
            return;
        }
        var save = document.getElementById('sunaq-save');
        var url = document.getElementById('sunaq-middleware-url');
        var key = document.getElementById('sunaq-api-key');
        var allowInsecureHttp = document.getElementById('sunaq-allow-insecure-http');
        var status = document.getElementById('sunaq-admin-status');

        save.addEventListener('click', function () {
            save.disabled = true;
            status.textContent = 'Speichere …';

            fetch(OC.generateUrl('/apps/sunaq/admin/config'), {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    'requesttoken': OC.requestToken
                },
                body: JSON.stringify({
                    middlewareUrl: url.value.trim(),
                    apiKey: key.value.trim(),
                    allowInsecureHttp: !!(allowInsecureHttp && allowInsecureHttp.checked)
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
