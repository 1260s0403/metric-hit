import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

const manifestPath = new URL('../work/automation/oborot-sceditor-caret-adapter/manifest.json', import.meta.url);
const adapterPath = new URL('../work/automation/oborot-sceditor-caret-adapter/caret-adapter.js', import.meta.url);

function adapterHarness(frameCount = 1) {
  const source = readFileSync(adapterPath, 'utf8');
  const listeners = new Map();
  const responses = [];
  const editorDocument = { designMode: 'off' };
  const body = { children: [], ownerDocument: editorDocument, parentElement: null, tagName: 'BODY',
    getAttribute: () => 'true' };
  const block = (tagName, content = '') => ({ nodeType: 1, tagName, textContent: content, children: [],
    ownerDocument: editorDocument, parentElement: body });
  body.children.push(block('P', ''), block('P', 'Первый абзац'));
  editorDocument.body = body;
  editorDocument.documentElement = { contains: (node) => node?.ownerDocument === editorDocument };
  const selection = { rangeCount: 0, isCollapsed: false, anchorNode: null, focusNode: null,
    removeAllRanges() { this.rangeCount = 0; }, addRange(range) { this.rangeCount = 1; this.isCollapsed = true;
      this.anchorNode = range.block; this.focusNode = range.block; } };
  editorDocument.getSelection = () => selection;
  editorDocument.createRange = () => ({ block: null, selectNodeContents(node) { this.block = node; }, collapse() {} });
  const iframe = { contentDocument: editorDocument };
  const outerDocument = {
    querySelectorAll: () => Array.from({ length: frameCount }, () => iframe),
    addEventListener: (type, listener) => listeners.set(type, listener),
    dispatchEvent: (event) => {
      if (event.type === 'oborot-caret-adapter:response') responses.push(event.detail);
      else listeners.get(event.type)?.(event);
      return true;
    },
  };
  class CustomEvent { constructor(type, options = {}) { this.type = type; this.detail = options.detail; } }
  vm.runInNewContext(source, { document: outerDocument, CustomEvent, Map, Set, String, Boolean, Math });
  const request = (operation, target) => {
    responses.length = 0;
    outerDocument.dispatchEvent(new CustomEvent('oborot-caret-adapter:request', { detail: { id: 'test', operation, target } }));
    return responses.at(-1).result;
  };
  return { request, selection };
}

test('manifest is local and constrained to Oborot draft URLs', () => {
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  assert.deepEqual(manifest.content_scripts[0].matches, ['https://oborot.ru/my/blog/*']);
  assert.equal('permissions' in manifest, false);
  assert.equal('host_permissions' in manifest, false);
  assert.equal('background' in manifest, false);
});

test('adapter uses the editable iframe Range and Selection APIs and has no upload or publish path', () => {
  const source = readFileSync(adapterPath, 'utf8');
  assert.match(source, /iframe\.sceditor-iframe/);
  assert.match(source, /createRange\(\)/);
  assert.match(source, /removeAllRanges\(\)/);
  assert.match(source, /addRange\(range\)/);
  assert.match(source, /editor_ambiguous/);
  assert.match(source, /target_ambiguous/);
  assert.match(source, /inline_image_not_at_target_boundary/);
  assert.doesNotMatch(source, /input\s*type\s*=\s*['\"]file/i);
  assert.doesNotMatch(source, /fetch\s*\(/);
  assert.doesNotMatch(source, /publish|опубликовать/i);
  assert.doesNotMatch(source, /preview/i);
});

test('adapter exposes a standard DOM control panel wired only to block listing and caret proof', () => {
  const source = readFileSync(adapterPath, 'utf8');
  assert.match(source, /function mountControlPanel\(\)/);
  assert.match(source, /oborot-caret-block/);
  assert.match(source, /oborot-caret-edge/);
  assert.match(source, /oborot-caret-set-and-prove/);
  assert.match(source, /const listed = listBlocks\(\)/);
  assert.match(source, /const proof = setCollapsedCaret\(\{/);
  assert.match(source, /renderResult\(proof\)/);
  assert.doesNotMatch(source, /createElement\(['"]input['"]\)/);
  assert.doesNotMatch(source, /fetch\s*\(/);
  assert.doesNotMatch(source, /chrome\.runtime|browser\.runtime/);
});

test('inline verification is only exposed after a proof-session preparation operation', () => {
  const source = readFileSync(adapterPath, 'utf8');
  assert.match(source, /function prepareInlineImage\(target\)/);
  assert.match(source, /const proof = setCollapsedCaret\(target\)/);
  assert.match(source, /sessions\.set\(sessionId/);
  assert.match(source, /function verifyInlineImage\(sessionId\)/);
  assert.match(source, /proof_session_not_found/);
  assert.match(source, /newImages\.length !== 1/);
});

test('DOM mock: a real collapsed caret proof is returned only for one explicit editor and target block', () => {
  const oneEditor = adapterHarness();
  const targets = oneEditor.request('listBlocks');
  const proof = oneEditor.request('setCollapsedCaret', { blockId: targets[0].blockId, edge: 'empty' });
  assert.deepEqual(JSON.parse(JSON.stringify(proof)), {
    editableDocument: true, collapsed: true, targetBlockId: targets[0].blockId,
    anchorInEditableDocument: true, focusInEditableDocument: true,
  });
  assert.equal(oneEditor.selection.anchorNode, oneEditor.selection.focusNode);
  assert.deepEqual(JSON.parse(JSON.stringify(adapterHarness(2).request('listBlocks'))), { error: 'editor_ambiguous' });
});
