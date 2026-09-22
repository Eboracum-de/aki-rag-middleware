(function () {
    'use strict';

    var messages = [];
    var conversationId = '';
    var editingIndex = null;
    var form;
    var input;
    var sendButton;
    var cancelEditButton;
    var status;
    var messageList;
    var retryButton;
    var chatList;
    var scopeInputs = [];
    var sourceScopeLabels = {
        documents: 'Dokumente',
        mailarchive: 'Mailarchiv',
        webarchive: 'Webarchiv',
        chatarchive: 'Chatarchiv',
        web: 'Web'
    };

    function appendInlineMarkdown(container, text) {
        var tokenRe = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\n]+\*|_[^_\n]+_|\[[^\]\n]{1,240}\]\((?:https?:\/\/)[^\s)]+\)|https?:\/\/[^\s<]+)/g;
        var last = 0;
        var match;
        while ((match = tokenRe.exec(text)) !== null) {
            if (match.index > last) {
                container.appendChild(document.createTextNode(text.slice(last, match.index)));
            }
            var token = match[0];
            if (token.charAt(0) === '`' && token.charAt(token.length - 1) === '`') {
                var code = document.createElement('code');
                code.textContent = token.slice(1, -1);
                container.appendChild(code);
            } else if (token.slice(0, 2) === '**' && token.slice(-2) === '**') {
                var strong = document.createElement('strong');
                strong.textContent = token.slice(2, -2);
                container.appendChild(strong);
            } else if ((token.charAt(0) === '*' && token.charAt(token.length - 1) === '*')
                    || (token.charAt(0) === '_' && token.charAt(token.length - 1) === '_')) {
                var em = document.createElement('em');
                em.textContent = token.slice(1, -1);
                container.appendChild(em);
            } else {
                var linkMatch = token.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
                var href = linkMatch ? linkMatch[2] : token;
                var label = linkMatch ? linkMatch[1] : token;
                var trailing = '';
                if (!linkMatch) {
                    while (/[.,;:!?)]$/.test(href)) {
                        trailing = href.slice(-1) + trailing;
                        href = href.slice(0, -1);
                    }
                }
                try {
                    var url = new URL(href, window.location.href);
                    if (url.protocol === 'http:' || url.protocol === 'https:') {
                        var a = document.createElement('a');
                        a.href = url.href;
                        a.textContent = label;
                        a.target = '_blank';
                        a.rel = 'noopener noreferrer';
                        container.appendChild(a);
                    } else {
                        container.appendChild(document.createTextNode(token));
                    }
                } catch (e) {
                    container.appendChild(document.createTextNode(token));
                }
                if (trailing) {
                    container.appendChild(document.createTextNode(trailing));
                }
            }
            last = tokenRe.lastIndex;
        }
        if (last < text.length) {
            container.appendChild(document.createTextNode(text.slice(last)));
        }
    }

    function splitMarkdownTableRow(line) {
        var value = String(line || '').trim();
        if (value.charAt(0) === '|') {
            value = value.slice(1);
        }
        if (value.charAt(value.length - 1) === '|') {
            value = value.slice(0, -1);
        }
        return value.split('|').map(function (cell) { return cell.trim(); });
    }

    function markdownTableAlignment(cell) {
        var value = String(cell || '').trim();
        if (!/^:?-{3,}:?$/.test(value)) {
            return null;
        }
        if (value.charAt(0) === ':' && value.charAt(value.length - 1) === ':') {
            return 'center';
        }
        if (value.charAt(value.length - 1) === ':') {
            return 'right';
        }
        if (value.charAt(0) === ':') {
            return 'left';
        }
        return '';
    }

    function isMarkdownTableStart(lines, index) {
        if (index + 1 >= lines.length || lines[index].indexOf('|') === -1) {
            return false;
        }
        var header = splitMarkdownTableRow(lines[index]);
        var separator = splitMarkdownTableRow(lines[index + 1]);
        if (header.length < 2 || separator.length !== header.length) {
            return false;
        }
        return separator.every(function (cell) {
            return markdownTableAlignment(cell) !== null;
        });
    }

    function appendMarkdownTable(container, lines, index) {
        var headers = splitMarkdownTableRow(lines[index]);
        var separators = splitMarkdownTableRow(lines[index + 1]);
        var alignments = separators.map(markdownTableAlignment);
        var wrapper = document.createElement('div');
        wrapper.className = 'akirag-table-wrap';
        var table = document.createElement('table');
        table.className = 'akirag-table';
        var thead = document.createElement('thead');
        var headRow = document.createElement('tr');
        headers.forEach(function (header, column) {
            var th = document.createElement('th');
            if (alignments[column]) { th.style.textAlign = alignments[column]; }
            appendInlineMarkdown(th, header);
            headRow.appendChild(th);
        });
        thead.appendChild(headRow);
        table.appendChild(thead);

        var tbody = document.createElement('tbody');
        var i = index + 2;
        while (i < lines.length && lines[i].trim() && lines[i].indexOf('|') !== -1) {
            var cells = splitMarkdownTableRow(lines[i]);
            if (cells.length !== headers.length) {
                break;
            }
            var tr = document.createElement('tr');
            cells.forEach(function (cell, column) {
                var td = document.createElement('td');
                if (alignments[column]) { td.style.textAlign = alignments[column]; }
                appendInlineMarkdown(td, cell);
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
            i += 1;
        }
        table.appendChild(tbody);
        wrapper.appendChild(table);
        container.appendChild(wrapper);
        return i;
    }

    function appendMarkdown(container, text) {
        var lines = String(text || '').replace(/\r\n?/g, '\n').split('\n');
        var i = 0;

        function appendParagraph(parts) {
            if (!parts.length) {
                return;
            }
            var p = document.createElement('p');
            appendInlineMarkdown(p, parts.join(' '));
            container.appendChild(p);
        }

        while (i < lines.length) {
            var line = lines[i];
            if (!line.trim()) {
                i += 1;
                continue;
            }

            if (isMarkdownTableStart(lines, i)) {
                i = appendMarkdownTable(container, lines, i);
                continue;
            }

            if (/^```/.test(line.trim())) {
                var language = line.trim().slice(3).trim();
                var codeLines = [];
                i += 1;
                while (i < lines.length && !/^```/.test(lines[i].trim())) {
                    codeLines.push(lines[i]);
                    i += 1;
                }
                if (i < lines.length) {
                    i += 1;
                }
                var pre = document.createElement('pre');
                var code = document.createElement('code');
                if (language) {
                    code.setAttribute('data-language', language);
                }
                code.textContent = codeLines.join('\n');
                pre.appendChild(code);
                container.appendChild(pre);
                continue;
            }

            if (/^\s*(?:---+|___+|\*\*\*+)\s*$/.test(line)) {
                container.appendChild(document.createElement('hr'));
                i += 1;
                continue;
            }

            var heading = line.match(/^(#{1,6})\s+(.+)$/);
            if (heading) {
                var h = document.createElement('h' + Math.min(6, heading[1].length + 2));
                appendInlineMarkdown(h, heading[2]);
                container.appendChild(h);
                i += 1;
                continue;
            }

            if (/^\s*[-*+]\s+/.test(line)) {
                var ul = document.createElement('ul');
                while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
                    var li = document.createElement('li');
                    appendInlineMarkdown(li, lines[i].replace(/^\s*[-*+]\s+/, ''));
                    ul.appendChild(li);
                    i += 1;
                }
                container.appendChild(ul);
                continue;
            }

            if (/^\s*\d+\.\s+/.test(line)) {
                var ol = document.createElement('ol');
                while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
                    var oli = document.createElement('li');
                    appendInlineMarkdown(oli, lines[i].replace(/^\s*\d+\.\s+/, ''));
                    ol.appendChild(oli);
                    i += 1;
                }
                container.appendChild(ol);
                continue;
            }

            if (/^\s*>\s?/.test(line)) {
                var quote = document.createElement('blockquote');
                var quoteParts = [];
                while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
                    quoteParts.push(lines[i].replace(/^\s*>\s?/, ''));
                    i += 1;
                }
                appendInlineMarkdown(quote, quoteParts.join(' '));
                container.appendChild(quote);
                continue;
            }

            var paragraph = [];
            while (i < lines.length && lines[i].trim()
                && !isMarkdownTableStart(lines, i)
                && !/^(#{1,6})\s+/.test(lines[i])
                && !/^```/.test(lines[i].trim())
                && !/^\s*(?:---+|___+|\*\*\*+)\s*$/.test(lines[i])
                && !/^\s*[-*+]\s+/.test(lines[i])
                && !/^\s*\d+\.\s+/.test(lines[i])
                && !/^\s*>\s?/.test(lines[i])) {
                paragraph.push(lines[i].trim());
                i += 1;
            }
            appendParagraph(paragraph);
        }
    }

    function formatTimestamp(value) {
        if (!value) {
            return '';
        }
        var date = new Date(value);
        if (isNaN(date.getTime())) {
            return '';
        }
        try {
            return new Intl.DateTimeFormat('de-DE', {
                year: 'numeric', month: '2-digit', day: '2-digit',
                hour: '2-digit', minute: '2-digit', second: '2-digit'
            }).format(date);
        } catch (e) {
            return date.toLocaleString();
        }
    }

    function formatSourceScopes(scopes) {
        if (!Array.isArray(scopes) || !scopes.length) {
            return '';
        }
        var labels = [];
        scopes.forEach(function (scope) {
            var value = String(scope || '').toLowerCase();
            var label = sourceScopeLabels[value];
            if (label && labels.indexOf(label) === -1) {
                labels.push(label);
            }
        });
        return labels.length ? 'Quellen: ' + labels.join(', ') : '';
    }

    function makeSmallButton(label, title, handler) {
        var button = document.createElement('button');
        button.type = 'button';
        button.className = 'button akirag-message-action';
        button.textContent = label;
        button.title = title;
        button.addEventListener('click', handler);
        return button;
    }

    function addMessage(role, content, index, createdAt, sourceScopes) {
        var wrapper = document.createElement('div');
        wrapper.className = 'akirag-message ' + (role === 'user' ? 'akirag-user' : 'akirag-assistant');

        var metaNode = document.createElement('div');
        metaNode.className = 'akirag-message-meta';
        var roleNode = document.createElement('span');
        roleNode.className = 'akirag-role';
        roleNode.textContent = role === 'user' ? 'Sie' : 'AKI';
        metaNode.appendChild(roleNode);
        var timestamp = formatTimestamp(createdAt);
        if (timestamp) {
            var timeNode = document.createElement('time');
            timeNode.className = 'akirag-message-time';
            timeNode.dateTime = createdAt;
            timeNode.textContent = timestamp;
            metaNode.appendChild(timeNode);
        }
        var sourceScopeText = role === 'assistant' ? formatSourceScopes(sourceScopes) : '';
        if (sourceScopeText) {
            var scopesNode = document.createElement('span');
            scopesNode.className = 'akirag-message-scopes';
            scopesNode.textContent = sourceScopeText;
            metaNode.appendChild(scopesNode);
        }

        var contentNode = document.createElement('div');
        contentNode.className = 'akirag-content';
        appendMarkdown(contentNode, content);

        wrapper.appendChild(metaNode);
        wrapper.appendChild(contentNode);

        if (role === 'user' && typeof index === 'number') {
            var controls = document.createElement('div');
            controls.className = 'akirag-message-actions';
            controls.appendChild(makeSmallButton('Erneut senden', 'Diese Frage ab diesem Punkt erneut an AKI senden', function () {
                resendAt(index);
            }));
            controls.appendChild(makeSmallButton('Bearbeiten & erneut senden', 'Diese Frage ändern und den Verlauf ab hier neu erzeugen', function () {
                beginEdit(index);
            }));
            wrapper.appendChild(controls);
        }

        messageList.appendChild(wrapper);
    }

    function renderConversation() {
        messageList.innerHTML = '';
        if (!messages.length) {
            addMessage('assistant', 'Was möchten Sie finden?');
        } else {
            messages.forEach(function (message, index) {
                addMessage(message.role, message.content, index, message.created_at || '', message.source_scopes || []);
            });
        }
        messageList.scrollTop = messageList.scrollHeight;
    }

    function selectedScopes() {
        return scopeInputs.filter(function (inputNode) {
            return inputNode.checked;
        }).map(function (inputNode) {
            return inputNode.value;
        });
    }

    function applyScopes(scopes) {
        var selected = Array.isArray(scopes) ? scopes : [];
        scopeInputs.forEach(function (inputNode) {
            inputNode.checked = selected.indexOf(inputNode.value) !== -1;
        });
    }

    function setBusy(busy, text) {
        sendButton.disabled = busy;
        input.disabled = busy;
        retryButton.disabled = busy;
        cancelEditButton.disabled = busy;
        scopeInputs.forEach(function (node) { node.disabled = busy; });
        Array.prototype.forEach.call(messageList.querySelectorAll('button'), function (button) {
            button.disabled = busy;
        });
        status.textContent = text || '';
    }

    function setRetryVisible(visible) {
        retryButton.hidden = !visible;
    }

    function apiRequest(path, method, payload) {
        var options = {
            method: method || 'GET',
            credentials: 'same-origin',
            headers: {'requesttoken': OC.requestToken}
        };
        if (payload !== undefined) {
            options.headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(payload);
        }
        return fetch(OC.generateUrl('/apps/akirag' + path), options).then(function (response) {
            return response.json().catch(function () { return {}; }).then(function (data) {
                if (!response.ok) {
                    throw new Error(data.error || ('HTTP ' + response.status));
                }
                return data;
            });
        });
    }

    function renderChatList(chats) {
        chatList.innerHTML = '';
        if (!Array.isArray(chats) || !chats.length) {
            var empty = document.createElement('span');
            empty.className = 'akirag-muted';
            empty.textContent = 'Noch keine gespeicherten Recherchen.';
            chatList.appendChild(empty);
            return;
        }
        chats.forEach(function (chat) {
            var row = document.createElement('div');
            row.className = 'akirag-chat-row' + (chat.id === conversationId ? ' is-active' : '');
            var open = document.createElement('button');
            open.type = 'button';
            open.className = 'akirag-chat-open';
            open.textContent = chat.title || 'Recherche';
            open.title = chat.updated_at || '';
            open.addEventListener('click', function () { loadChat(chat.id); });
            var tools = document.createElement('span');
            tools.className = 'akirag-chat-tools';
            var rename = makeSmallButton('✎', 'Recherche umbenennen', function (event) {
                event.stopPropagation();
                var title = window.prompt('Titel der Recherche', chat.title || '');
                if (title && title.trim()) {
                    apiRequest('/chats/' + encodeURIComponent(chat.id) + '/rename', 'POST', {title: title.trim()})
                        .then(loadChatList)
                        .catch(function (error) { status.textContent = error.message; });
                }
            });
            var remove = makeSmallButton('×', 'Recherche löschen', function (event) {
                event.stopPropagation();
                if (!window.confirm('Diese Recherche löschen?')) { return; }
                apiRequest('/chats/' + encodeURIComponent(chat.id), 'DELETE').then(function () {
                    if (conversationId === chat.id) { resetSearch(); }
                    loadChatList();
                }).catch(function (error) { status.textContent = error.message; });
            });
            tools.appendChild(rename);
            tools.appendChild(remove);
            row.appendChild(open);
            row.appendChild(tools);
            chatList.appendChild(row);
        });
    }

    function loadChatList() {
        return apiRequest('/chats', 'GET').then(function (data) {
            renderChatList(data.chats || []);
        }).catch(function (error) {
            chatList.textContent = 'Chatarchiv nicht verfügbar: ' + error.message;
        });
    }

    function loadChat(id) {
        setBusy(true, 'Recherche wird geladen …');
        apiRequest('/chats/' + encodeURIComponent(id), 'GET').then(function (data) {
            var chat = data.chat || {};
            conversationId = chat.id || id;
            messages = Array.isArray(chat.messages) ? chat.messages : [];
            if (Array.isArray(chat.scopes) && chat.scopes.length) {
                applyScopes(chat.scopes);
            }
            editingIndex = null;
            input.value = '';
            sendButton.textContent = 'Suchen';
            cancelEditButton.hidden = true;
            renderConversation();
            setBusy(false, '');
            loadChatList();
            input.focus();
        }).catch(function (error) {
            setBusy(false, 'Fehler: ' + error.message);
        });
    }

    function runQueryRequest() {
        setRetryVisible(false);
        setBusy(true, 'Suche läuft …');

        return apiRequest('/chat', 'POST', {
            messages: messages,
            sourceScopes: selectedScopes(),
            conversationId: conversationId
        }).then(function (data) {
            var answer = data.content || 'Keine Antwort erhalten.';
            var assistant = {
                role: 'assistant',
                content: answer,
                created_at: data.message_created_at || new Date().toISOString(),
                source_scopes: Array.isArray(data.source_scopes) ? data.source_scopes : []
            };
            if (Array.isArray(data.sources) && data.sources.length) {
                assistant.sources = data.sources;
            }
            messages.push(assistant);
            if (data.conversation && data.conversation.id) {
                conversationId = data.conversation.id;
            }
            renderConversation();
            setBusy(false, '');
            loadChatList();
        }).catch(function (error) {
            renderConversation();
            addMessage('assistant', 'Fehler: ' + error.message);
            messageList.scrollTop = messageList.scrollHeight;
            setBusy(false, '');
            setRetryVisible(true);
        });
    }

    function sendBranch(index, text) {
        var prefix = typeof index === 'number' ? messages.slice(0, index) : messages.slice();
        messages = prefix;
        messages.push({role: 'user', content: text, created_at: new Date().toISOString()});
        editingIndex = null;
        cancelEditButton.hidden = true;
        sendButton.textContent = 'Suchen';
        input.value = '';
        renderConversation();
        return runQueryRequest();
    }

    function submitQuery(text) {
        if (editingIndex !== null) {
            return sendBranch(editingIndex, text);
        }
        return sendBranch(null, text);
    }

    function resendAt(index) {
        if (!messages[index] || messages[index].role !== 'user') {
            return;
        }
        sendBranch(index, messages[index].content);
    }

    function beginEdit(index) {
        if (!messages[index] || messages[index].role !== 'user') {
            return;
        }
        editingIndex = index;
        input.value = messages[index].content;
        sendButton.textContent = 'Geändert senden';
        cancelEditButton.hidden = false;
        status.textContent = 'Frage wird ab diesem Punkt neu gesendet.';
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
    }

    function cancelEdit() {
        editingIndex = null;
        input.value = '';
        sendButton.textContent = 'Suchen';
        cancelEditButton.hidden = true;
        status.textContent = '';
        input.focus();
    }

    function resetSearch() {
        messages = [];
        conversationId = '';
        editingIndex = null;
        input.value = '';
        sendButton.textContent = 'Suchen';
        cancelEditButton.hidden = true;
        setRetryVisible(false);
        renderConversation();
        status.textContent = '';
        loadChatList();
        input.focus();
    }

    function init() {
        form = document.getElementById('akirag-form');
        if (!form) {
            return;
        }
        input = document.getElementById('akirag-input');
        sendButton = document.getElementById('akirag-send');
        cancelEditButton = document.getElementById('akirag-cancel-edit');
        status = document.getElementById('akirag-status');
        messageList = document.getElementById('akirag-messages');
        retryButton = document.getElementById('akirag-retry');
        chatList = document.getElementById('akirag-chat-list');
        scopeInputs = Array.prototype.slice.call(document.querySelectorAll('input[name="akirag-scope"]'));

        form.addEventListener('submit', function (event) {
            event.preventDefault();
            var text = input.value.trim();
            if (!text || sendButton.disabled) {
                return;
            }
            submitQuery(text);
        });

        input.addEventListener('keydown', function (event) {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                if (typeof form.requestSubmit === 'function') {
                    form.requestSubmit();
                } else {
                    sendButton.click();
                }
            }
        });

        document.getElementById('akirag-new').addEventListener('click', resetSearch);
        cancelEditButton.addEventListener('click', cancelEdit);
        retryButton.addEventListener('click', function () {
            if (!retryButton.disabled && messages.length && messages[messages.length - 1].role === 'user') {
                runQueryRequest();
            }
        });
        renderConversation();
        loadChatList();
        input.focus();
    }

    document.addEventListener('DOMContentLoaded', init);
}());
