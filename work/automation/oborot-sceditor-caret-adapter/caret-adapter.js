(() => {
  'use strict';

  const REQUEST = 'oborot-caret-adapter:request';
  const RESPONSE = 'oborot-caret-adapter:response';
  const sessions = new Map();
  let nextSessionId = 1;

  const error = (code) => ({ error: code });
  const text = (node) => String(node?.textContent ?? '').replace(/\s+/g, ' ').trim();
  const hash = (value) => {
    let result = 2166136261;
    for (const char of value) {
      result ^= char.charCodeAt(0);
      result = Math.imul(result, 16777619);
    }
    return (result >>> 0).toString(16);
  };

  function editableFrame() {
    const frames = [...document.querySelectorAll('iframe.sceditor-iframe')].filter((frame) => {
      const editorDocument = frame.contentDocument;
      const body = editorDocument?.body;
      return Boolean(body && (body.isContentEditable || body.getAttribute('contenteditable') === 'true'
        || String(editorDocument.designMode).toLowerCase() === 'on'));
    });
    return frames.length === 1 ? { frame: frames[0], editorDocument: frames[0].contentDocument } : error('editor_ambiguous');
  }

  function blocks(editorDocument) {
    return [...editorDocument.body.children].filter((node) => node.nodeType === 1 && node.tagName !== 'BR');
  }

  function blockId(block, index) {
    return `block:${index}:${hash(`${block.tagName}:${text(block)}`)}`;
  }

  function listBlocks() {
    const editor = editableFrame();
    if (editor.error) return editor;
    return blocks(editor.editorDocument).map((block, index) => ({
      blockId: blockId(block, index), tagName: block.tagName.toLowerCase(), text: text(block),
      empty: text(block) === '' && [...block.children].every((child) => child.tagName === 'BR'),
    }));
  }

  function resolveTarget(target) {
    if (!target || typeof target.blockId !== 'string' || !['start', 'end', 'empty'].includes(target.edge)) {
      return error('target_not_found');
    }
    const editor = editableFrame();
    if (editor.error) return editor;
    const matches = blocks(editor.editorDocument).filter((block, index) => blockId(block, index) === target.blockId);
    if (matches.length !== 1) return error(matches.length > 1 ? 'target_ambiguous' : 'target_not_found');
    if (target.edge === 'empty' && !(text(matches[0]) === '' && [...matches[0].children].every((child) => child.tagName === 'BR'))) {
      return error('target_not_empty');
    }
    return { ...editor, block: matches[0], target };
  }

  function contains(editorDocument, node) {
    return Boolean(node && node.ownerDocument === editorDocument && editorDocument.documentElement.contains(node));
  }

  function targetForNode(editorDocument, node) {
    let current = node?.nodeType === 1 ? node : node?.parentElement;
    while (current && current.parentElement !== editorDocument.body) current = current.parentElement;
    if (!current || current.parentElement !== editorDocument.body) return null;
    const index = blocks(editorDocument).indexOf(current);
    return index < 0 ? null : blockId(current, index);
  }

  function readSelection() {
    const editor = editableFrame();
    if (editor.error) return editor;
    const selection = editor.editorDocument.getSelection();
    const anchorInEditableDocument = contains(editor.editorDocument, selection?.anchorNode);
    const focusInEditableDocument = contains(editor.editorDocument, selection?.focusNode);
    return {
      editableDocument: true,
      collapsed: Boolean(selection && selection.rangeCount === 1 && selection.isCollapsed),
      targetBlockId: anchorInEditableDocument && focusInEditableDocument && selection.anchorNode === selection.focusNode
        ? targetForNode(editor.editorDocument, selection.anchorNode) : null,
      anchorInEditableDocument,
      focusInEditableDocument,
    };
  }

  function setCollapsedCaret(target) {
    const resolved = resolveTarget(target);
    if (resolved.error) return resolved;
    const range = resolved.editorDocument.createRange();
    range.selectNodeContents(resolved.block);
    range.collapse(target.edge !== 'end');
    const selection = resolved.editorDocument.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    const proof = readSelection();
    return proof.collapsed && proof.targetBlockId === target.blockId
      && proof.anchorInEditableDocument && proof.focusInEditableDocument ? proof : error('selection_not_set');
  }

  function directImages(block) {
    return [...block.children].filter((child) => child.tagName === 'IMG');
  }

  function prepareInlineImage(target) {
    const proof = setCollapsedCaret(target);
    if (proof.error) return proof;
    const resolved = resolveTarget(target);
    if (resolved.error) return resolved;
    const sessionId = `inline-image:${nextSessionId++}`;
    sessions.set(sessionId, { target, block: resolved.block, imageNodes: new Set(directImages(resolved.block)) });
    return { sessionId, selectionProof: proof };
  }

  function verifyInlineImage(sessionId) {
    const session = sessions.get(sessionId);
    if (!session) return error('proof_session_not_found');
    sessions.delete(sessionId);
    const resolved = resolveTarget(session.target);
    if (resolved.error || resolved.block !== session.block) return error('target_changed');
    const newImages = directImages(resolved.block).filter((image) => !session.imageNodes.has(image));
    if (newImages.length !== 1) return error('inline_image_not_exactly_one');
    const image = newImages[0];
    const exact = session.target.edge === 'start' ? resolved.block.firstElementChild === image
      : session.target.edge === 'end' ? resolved.block.lastElementChild === image
        : [...resolved.block.children].every((child) => child === image || child.tagName === 'BR');
    return exact ? { verified: true, sessionId, targetBlockId: session.target.blockId, edge: session.target.edge }
      : error('inline_image_not_at_target_boundary');
  }

  const operations = { listBlocks, readSelection, setCollapsedCaret, prepareInlineImage, verifyInlineImage };

  function displayValue(value) {
    return JSON.stringify(value, null, 2);
  }

  function mountControlPanel() {
    if (typeof document.createElement !== 'function' || document.getElementById?.('oborot-caret-adapter-panel')) return;
    // Oborot embeds its editor in an outer frame, which in turn owns the
    // SCEditor iframe. The script is deliberately present in every allowed
    // frame, but only this outer editor frame is allowed to render controls.
    if (editableFrame().error) return;
    const panel = document.createElement('section');
    panel.id = 'oborot-caret-adapter-panel';
    panel.setAttribute('aria-label', 'Проверка позиции курсора Oborot');
    panel.style.cssText = [
      'position:fixed', 'right:16px', 'bottom:16px', 'z-index:2147483647', 'width:360px',
      'padding:12px', 'border:1px solid #385170', 'border-radius:8px', 'background:#fff',
      'color:#152536', 'box-shadow:0 6px 24px rgba(0,0,0,.25)', 'font:14px/1.4 Arial,sans-serif',
    ].join(';');
    const title = document.createElement('strong');
    title.textContent = 'Курсор в тексте';
    const hint = document.createElement('p');
    hint.textContent = 'Выберите один блок и его границу. Панель только ставит и проверяет текстовый курсор.';
    const refresh = document.createElement('button');
    refresh.type = 'button'; refresh.id = 'oborot-caret-refresh-blocks'; refresh.textContent = 'Обновить блоки';
    const blockLabel = document.createElement('label');
    blockLabel.htmlFor = 'oborot-caret-block'; blockLabel.textContent = 'Блок';
    const blockSelect = document.createElement('select');
    blockSelect.id = 'oborot-caret-block'; blockSelect.setAttribute('aria-label', 'Блок текста');
    blockSelect.style.cssText = 'display:block;width:100%;margin:4px 0 10px';
    const edgeLabel = document.createElement('label');
    edgeLabel.htmlFor = 'oborot-caret-edge'; edgeLabel.textContent = 'Граница';
    const edgeSelect = document.createElement('select');
    edgeSelect.id = 'oborot-caret-edge'; edgeSelect.setAttribute('aria-label', 'Граница блока');
    edgeSelect.style.cssText = 'display:block;width:100%;margin:4px 0 10px';
    for (const [value, label] of [['start', 'Начало'], ['end', 'Конец'], ['empty', 'Пустой блок']]) {
      const option = document.createElement('option'); option.value = value; option.textContent = label; edgeSelect.append(option);
    }
    const prove = document.createElement('button');
    prove.type = 'button'; prove.id = 'oborot-caret-set-and-prove'; prove.textContent = 'Поставить и проверить курсор';
    const result = document.createElement('pre');
    result.id = 'oborot-caret-selection-proof'; result.setAttribute('aria-live', 'polite');
    result.style.cssText = 'white-space:pre-wrap;overflow-wrap:anywhere;margin:10px 0 0;padding:8px;background:#f4f7fa';
    panel.append(title, hint, refresh, blockLabel, blockSelect, edgeLabel, edgeSelect, prove, result);

    let listedBlocks = [];
    const selectedBlock = () => listedBlocks.find((item) => item.blockId === blockSelect.value) ?? null;
    const updateEmptyEdge = () => {
      const empty = edgeSelect.querySelector('option[value="empty"]');
      if (!empty) return;
      empty.disabled = !selectedBlock()?.empty;
      if (empty.disabled && edgeSelect.value === 'empty') edgeSelect.value = 'start';
    };
    const renderResult = (value) => { result.textContent = displayValue(value); };
    const loadBlocks = () => {
      const listed = listBlocks();
      blockSelect.replaceChildren();
      if (listed.error) { listedBlocks = []; prove.disabled = true; renderResult(listed); return; }
      listedBlocks = listed;
      for (const item of listedBlocks) {
        const option = document.createElement('option');
        option.value = item.blockId;
        option.textContent = `${item.tagName} · ${item.empty ? 'пустой' : item.text.slice(0, 90)}`;
        blockSelect.append(option);
      }
      prove.disabled = listedBlocks.length !== 1 && !blockSelect.value;
      updateEmptyEdge();
      renderResult({ blocks: listedBlocks.map(({ blockId, tagName, empty }) => ({ blockId, tagName, empty })) });
    };
    refresh.addEventListener('click', loadBlocks);
    blockSelect.addEventListener('change', updateEmptyEdge);
    prove.addEventListener('click', () => {
      const block = selectedBlock();
      if (!block) { renderResult(error('target_not_found')); return; }
      const proof = setCollapsedCaret({ blockId: block.blockId, edge: edgeSelect.value });
      renderResult(proof);
    });
    loadBlocks();
    (document.body ?? document.documentElement).append(panel);
  }

  document.addEventListener(REQUEST, (event) => {
    const request = event.detail ?? {};
    const operation = operations[request.operation];
    const result = operation ? operation(request.target ?? request.sessionId) : error('unsupported_operation');
    document.dispatchEvent(new CustomEvent(RESPONSE, { detail: { id: request.id ?? null, result } }));
  });
  mountControlPanel();
})();
