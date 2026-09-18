<?php
return [
    'routes' => [
        ['name' => 'page#index', 'url' => '/', 'verb' => 'GET'],
        ['name' => 'chat#send', 'url' => '/chat', 'verb' => 'POST'],
        ['name' => 'chat#listChats', 'url' => '/chats', 'verb' => 'GET'],
        ['name' => 'chat#load', 'url' => '/chats/{id}', 'verb' => 'GET'],
        ['name' => 'chat#rename', 'url' => '/chats/{id}/rename', 'verb' => 'POST'],
        ['name' => 'chat#delete', 'url' => '/chats/{id}', 'verb' => 'DELETE'],
        ['name' => 'admin#save', 'url' => '/admin/config', 'verb' => 'POST'],
    ],
];
