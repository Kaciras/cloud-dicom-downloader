import asyncio
import re
import sys
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from playwright.async_api import Playwright, Response, async_playwright, Page
from pydicom import dcmread
from tqdm import tqdm
from yarl import URL

from crawlers._utils import pathify


async def _select_text(context, selector: str):
	return await (await context.wait_for_selector(selector)).text_content()


@dataclass(frozen=True, eq=False)
class _FitImageStudyInfo:
	patient: str
	kind: str
	time: str
	total: int
	series: dict[str, tuple[str, int]]


_RE_STUDY_SIZE = re.compile(r"序列:\s(\d+)\s影像:\s(\d+)")
_RE_SERIES_SIZE = re.compile(r"共 (\d+)张")  # 共 65张


async def wait_study_info(page: Page):
	patient = await _select_text(page, ".patientInfo > *:nth-child(1) > .name")
	kind = await _select_text(page, ".patientInfo > *:nth-child(2) > .value")
	time = await _select_text(page, ".patientInfo > *:nth-child(5) > .value")

	title = await page.wait_for_selector(".title > small")
	matches = _RE_STUDY_SIZE.search(await title.text_content())
	series, slices = int(matches.group(1)), int(matches.group(2))

	tabs, series_table = [], {}
	while len(tabs) < series:
		tabs = await page.query_selector_all("li[data-seriesuuid]")
		await asyncio.sleep(0.5)

	for tab in tabs:
		sid = await tab.get_attribute("data-seriesuuid")
		name = await _select_text(tab, ".desc > .text")
		size = await _select_text(tab, ".desc > .total")
		series_table[sid] = (
			name,
			int(_RE_SERIES_SIZE.match(size).group(1)),
		)

	patient, time = patient.strip(), re.sub(r"\D", "", time)
	return _FitImageStudyInfo(patient, kind, time, slices, series_table)


async def x(playwright: Playwright, url: str):
	browser = await playwright.chromium.launch()
	context = await browser.new_context()
	waiter = asyncio.Event()

	# 关闭窗口并不结束浏览器进程，只能依靠页面计数来判断。
	# https://github.com/microsoft/playwright/issues/2946
	def check_all_closed():
		if len(context.pages) == 0:
			waiter.set()

	context.on("page", lambda x: x.on("close", check_all_closed))
	page = await context.new_page()
	context.on("response", dump_http)

	await page.goto(url, wait_until="commit")
	study = await wait_study_info(page)
	print(f"{study.patient}，序列数：{len(study.series)}，共 {study.total} 张图")

	global _total_files, progress
	_total_files = study.total
	progress = tqdm(total=study.total, initial=_downloaded_count, unit="张", file=sys.stdout)

	if _downloaded_count < study.total:
		await waiter.wait()

	progress.close()
	await browser.close(reason="Close as completed.")

	out_dir = Path(f"download/{_study_id}")
	for s in out_dir.iterdir():
		real_name, size = study.series[s.name]
		s.rename(s.with_name(real_name))

	final_name = pathify(f"{study.patient}-{study.kind}-{study.time}")
	print(f"下载完成，保存位置 {out_dir.rename(out_dir.with_name(final_name))}")


progress = None
_downloaded_count = 0
_total_files = 2**31
_desc_re = re.compile(r"\d+\^(.+)")  # 052006^肺部CT
_study_id = None
_info = None


async def dump_http(response: Response):
	global _downloaded_count, _total_files, _study_id, _info

	url = URL(response.request.url).path
	if not url.endswith(".dcm"):
		return
	_, _, _, _study_id, series_id, _, name = url.split("/")

	body = await response.body()
	ds = dcmread(BytesIO(body))

	dir_ = Path(f"download/{_study_id}/{series_id}/{ds.InstanceNumber}.dcm")
	dir_.parent.mkdir(parents=True, exist_ok=True)
	dir_.write_bytes(body)

	_downloaded_count += 1
	if progress:
		progress.update()
	if _downloaded_count == _total_files:
		await response.frame.page.close()


async def run(share_url):
	async with async_playwright() as playwright:
		await x(playwright, share_url)

