import * as vscode from 'vscode';
import { LanguageClient, LanguageClientOptions, ServerOptions } from 'vscode-languageclient/node';

export function activate(context: vscode.ExtensionContext) {
    const serverOptions: ServerOptions = {
        command: "python",
        args: [context.extensionPath + "/src/server/main.py"]
    };
    const clientOptions: LanguageClientOptions = {
        documentSelector: [{ scheme: 'file', language: 'bolt' }]
    };
    const client = new LanguageClient('boltLanguageServer', 'Bolt Language Server', serverOptions, clientOptions);
    client.start();
    context.subscriptions.push(client);
}
