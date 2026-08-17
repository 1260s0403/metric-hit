from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


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
            browser=p.chromium.launch(channel='msedge',headless=True); page=browser.new_page(viewport={'width':390,'height':844}); page.set_default_timeout(5000); errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)));page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None)
            page.goto(f'http://127.0.0.1:{port}/?view=projects');expect(page.get_by_test_id('projects-new')).to_be_visible();assert page.get_by_test_id('tab-projects').get_attribute('aria-current')=='page'
            page.wait_for_timeout(300)
            expect(page.get_by_test_id('projects-new')).to_have_count(1)
            initial_ids = page.locator('[data-testid^="project-card-"]').evaluate_all("cards => cards.map(card => card.dataset.testid)")
            assert len(initial_ids) == len(set(initial_ids))

            page.get_by_test_id('projects-new').click();expect(page.get_by_test_id('project-parent')).to_be_visible()
            page.get_by_test_id('project-title').fill('Проект Ёлка');page.get_by_test_id('project-description').fill('text');page.get_by_test_id('project-save').click()
            card=page.locator('[data-testid^="project-card-"]').filter(has_text='Проект Ёлка');expect(card).to_have_count(1)
            project_id=card.get_attribute('data-testid').removeprefix('project-card-')

            page.reload();expect(page.locator('[data-testid^="project-card-"]').filter(has_text='Проект Ёлка')).to_have_count(1);page.wait_for_timeout(300)
            ids = page.locator('[data-testid^="project-card-"]').evaluate_all("cards => cards.map(card => card.dataset.testid)")
            assert len(ids) == len(set(ids))
            page.get_by_test_id(f'project-card-{project_id}').locator(':scope > .row-disclosure > summary').click();page.get_by_test_id(f'project-open-{project_id}').click();expect(page.locator(f'#project-{project_id} h2')).to_have_text('Проект Ёлка');assert page.url.endswith(f'#project-{project_id}')

            page.goto(f'http://127.0.0.1:{port}/?view=projects');expect(page.get_by_test_id('projects-new')).to_be_visible();page.wait_for_timeout(300);page.get_by_test_id('projects-new').click()
            page.get_by_test_id('project-parent').select_option(project_id);page.get_by_test_id('project-title').fill('Подпроект Ёлка');page.get_by_test_id('project-description').fill('child');page.get_by_test_id('project-save').click()
            card=page.get_by_test_id(f'project-card-{project_id}');page.wait_for_timeout(300);card.locator('.subproject-disclosure > summary').click()
            child=page.locator('.subproject-line[data-testid^="project-card-"]').filter(has_text='Подпроект Ёлка');expect(child).to_have_count(1);expect(child.get_by_test_id('project-scope-kind')).to_contain_text('Проект Ёлка')
            child_id=child.get_attribute('data-testid').removeprefix('project-card-');child.locator('.row-disclosure > summary').click();child.get_by_text('Редактировать').click();page.get_by_test_id('project-description').fill('updated');page.get_by_test_id('project-save').click();page.goto(f'http://127.0.0.1:{port}/?view=projects&project_id={child_id}#project-{child_id}');expect(page.locator(f'#project-{child_id} > p')).to_have_text('updated')
            page.goto(f'http://127.0.0.1:{port}/?view=projects');page.wait_for_timeout(300);card=page.get_by_test_id(f'project-card-{project_id}');card.locator(':scope > .row-disclosure > summary').click();page.get_by_test_id(f'project-archive-{project_id}').click();expect(card.get_by_text('Архивный')).to_be_visible();assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth') and not errors
            browser.close()
    finally: process.terminate();process.wait(timeout=5)
