# Oborot SCEditor Caret Adapter

This is local extension source only. It is not installed, enabled, injected into Oborot, or connected to a draft by this delivery.

## What it does

- Runs only on `https://oborot.ru/my/blog/*` when an owner later installs and explicitly enables it.
- Refuses unless exactly one editable `iframe.sceditor-iframe` is present.
- Lists direct editor-body blocks with deterministic IDs; a future operator chooses one explicit ID and an edge: `start`, `end`, or `empty`.
- Uses the iframe document's `Range` and `Selection` APIs to set a collapsed caret and returns a proof that the selection is inside the chosen block.
- Creates a one-time proof session before a manual SCEditor image command. After that command, it verifies exactly one new direct `IMG` at the chosen boundary.

It does not upload a file, operate the SCEditor toolbar, alter preview covers, submit a draft, publish, read credentials, or persist draft content.

## Later installation requires a separate owner confirmation

Before any live use, the owner must explicitly approve this exact action: load the unpacked extension from this folder in the browser's extension developer page and enable it for the current browser profile. The requested scope is one content script restricted by the manifest to `https://oborot.ru/my/blog/*`; the manifest has no `permissions`, no background worker, no network access, and no access to other sites.

After that approval, enabling it is still not approval to upload, edit a draft, or publish. Each of those actions remains separately confirmed.

## Adapter message contract

The page-world caller dispatches `oborot-caret-adapter:request` on `document`; the adapter responds with `oborot-caret-adapter:response`.

```js
document.dispatchEvent(new CustomEvent('oborot-caret-adapter:request', {
  detail: { id: 'request-1', operation: 'setCollapsedCaret', target: { blockId, edge: 'empty' } },
}));
```

Allowed operations: `listBlocks`, `readSelection`, `setCollapsedCaret`, `prepareInlineImage`, and `verifyInlineImage`. Preview-cover operations, uploads, clicks, submission, and publication are intentionally unsupported.
