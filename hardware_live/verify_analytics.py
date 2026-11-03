"""Read-only browser verification against fresh physical analytics. No fixtures."""
import json
from pathlib import Path
import urllib.request
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'dev/analytics'
OUT.mkdir(exist_ok=True)
report={'checks':{},'errors':[]}
with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge')
    page=browser.new_page(viewport={'width':1440,'height':1100},device_scale_factor=1)
    page.on('pageerror',lambda e:report['errors'].append(str(e)))
    page.goto('http://127.0.0.1:8767')
    page.wait_for_function("document.querySelector('#connection').textContent.includes('Physical')",timeout=20000)
    report['checks']['physical_bridge_visible']='Physical UART' in page.locator('#connection').inner_text()
    page.wait_for_function("document.querySelector('#profile').options.length===8")
    report['checks']['all_profiles']=page.locator('#profile option').count()==8
    report['checks']['all_architectures']=page.locator('#mode option').count()==4
    report['checks']['no_page_overflow_desktop']=page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(OUT/'desktop.png'),full_page=True)
    if page.locator('#matrix td.heat:not(.missing)').count():
        page.locator('#matrix td.heat:not(.missing) button').first.click()
        report['checks']['chart_marks_visible']=page.locator('#latency svg rect').count()>0
        report['checks']['stage_table_populated']=page.locator('#stages tbody tr').count()==5
        report['checks']['quality_populated']=page.locator('#quality strong').count()==4
        page.select_option('#heatMetric','payload_mbps')
        report['checks']['matrix_filter_keeps_entries']=page.locator('#matrix td.heat:not(.missing)').count()>0
        with page.expect_download() as d:page.locator('#csv').click()
        report['checks']['csv_download']=d.value.suggested_filename.endswith('.csv')
        with page.expect_download() as d:page.locator('#download').click()
        report['checks']['evidence_download']=d.value.suggested_filename.endswith('.json')
        page.select_option('#heatMetric','latency_us')
    page.set_viewport_size({'width':390,'height':844})
    report['checks']['no_page_overflow_mobile']=page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(OUT/'mobile.png'),full_page=True)
    page.emulate_media(media='print')
    report['checks']['print_controls_hidden']=not page.locator('#start').is_visible()
    browser.close()
report['checks']['no_browser_errors']=not report['errors']
(OUT/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
if not all(report['checks'].values()):raise SystemExit(1)
