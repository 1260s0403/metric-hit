from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def test_projects_create_edit_archive_in_browser(tmp_path: Path) -> None:
    db=tmp_path/'projects-e2e.sqlite'; subprocess.run(['node','scripts/init-memory.mjs',str(db)],check=True,capture_output=True)
    with socket.socket() as probe: probe.bind(('127.0.0.1',0)); port=probe.getsockname()[1]
    process=subprocess.Popen([sys.executable,'-m','metrichit_os','operator-panel','--db',str(db),'--port',str(port)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.1): break
            except OSError: time.sleep(.1)
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True); page=browser.new_page(viewport={'width':390,'height':844}); errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)));page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None)
            page.goto(f'http://127.0.0.1:{port}/?view=projects');page.wait_for_timeout(200);assert page.get_by_test_id('tab-projects').get_attribute('aria-current')=='page'
            page.get_by_test_id('projects-new').click();page.get_by_test_id('project-title').fill('Проект Ёлка');page.get_by_test_id('project-description').fill('text');page.get_by_test_id('project-save').click();page.wait_for_timeout(200)
            card=page.locator('[data-testid^="project-card-"]').filter(has_text='Проект Ёлка');assert card.count()==1;card.get_by_text('Архивировать').click();page.wait_for_timeout(150);assert 'archived' in card.inner_text();assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth') and not errors
            browser.close()
    finally: process.terminate();process.wait(timeout=5)
