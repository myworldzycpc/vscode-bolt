import * as vscode from 'vscode';
import * as net from 'net';
import { LanguageClient, LanguageClientOptions, ServerOptions, StreamInfo } from 'vscode-languageclient/node';

const port = 5000;
const hostname = '127.0.0.1';

export function activate(context: vscode.ExtensionContext) {
    const serverOptions: ServerOptions = {
        command: "python",
        args: [context.extensionPath + "/src/server/main.py"]
    };
    // const serverOptions: ServerOptions = () => {
    //     return new Promise<StreamInfo>((resolve, reject) => {
    //         const socket = net.connect(port, hostname, () => {
    //             resolve({
    //                 reader: socket,
    //                 writer: socket
    //             })
    //         })
    //         socket.on('error', (err) => {
    //             reject(err);
    //         })
    //     });
    // }
    const clientOptions: LanguageClientOptions = {
        documentSelector: [{ scheme: 'file', language: 'bolt' }]
    };
    const client = new LanguageClient('boltLanguageServer', 'Bolt Language Server', serverOptions, clientOptions);
    client.start();
    context.subscriptions.push(client);
}
