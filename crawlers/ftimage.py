import asyncio
import re
import sys
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from playwright.async_api import Response, Page, BrowserContext
from pydicom import dcmread
from tqdm import tqdm
from yarl import URL

from crawlers._browser import wait_text, run_with_browser, PlaywrightCrawler
from crawlers._utils import suggest_save_dir


@dataclass(frozen=True, eq=False)
class _FitImageStudyInfo:
	patient: str
	kind: str
	time: str
	total: int
	series: dict[str, tuple[str, int]]


_RE_STUDY_SIZE = re.compile(r"序列:\s(\d+)\s影像:\s(\d+)")
_RE_SERIES_SIZE = re.compile(r"共 (\d+)张")


async def wait_study_info(page: Page):
	patient = await wait_text(page, ".patientInfo > *:nth-child(1) > .name")
	kind = await wait_text(page, ".patientInfo > *:nth-child(2) > .value")
	time = await wait_text(page, ".patientInfo > *:nth-child(5) > .value")

	title = await page.wait_for_selector(".title > small")
	matches = _RE_STUDY_SIZE.search(await title.text_content())
	series, slices = int(matches.group(1)), int(matches.group(2))

	tabs, series_table = [], {}
	while len(tabs) < series:
		tabs = await page.query_selector_all("li[data-seriesuuid]")
		await asyncio.sleep(0.5)

	for tab in tabs:
		sid = await tab.get_attribute("data-seriesuuid")
		name = await wait_text(tab, ".desc > .text")
		size = await wait_text(tab, ".desc > .total")
		series_table[sid] = (
			name,
			int(_RE_SERIES_SIZE.match(size).group(1)),
		)

	patient, time = patient.strip(), re.sub(r"\D", "", time)
	return _FitImageStudyInfo(patient, kind, time, slices, series_table)


class FitImageDownloader(PlaywrightCrawler):
	"""
	飞图医疗影像平台的下载器，该平台自称被 3000 的多家医院采用。
	"""
	_total = 0xFFFFFFFF
	_downloaded = 0
	_study_id = None
	_progress: tqdm | None = None

	share_url: str

	def __init__(self, share_url: str):
		super().__init__()
		self.share_url = share_url

	async def _on_response(self, response: Response):
		asset_name = URL(response.request.url).path

		if not asset_name.endswith(".dcm"):
			return

		_, _, _, self._study_id, series_id, _, _ = asset_name.split("/")
		body = await response.body()
		index = dcmread(BytesIO(body)).InstanceNumber

		dir_ = Path(f"download/{self._study_id}/{series_id}/{index}.dcm")
		dir_.parent.mkdir(parents=True, exist_ok=True)
		dir_.write_bytes(body)

		self._downloaded += 1

		if self._progress:
			self._progress.update()

		if self._downloaded == self._total:
			await response.frame.page.context.close()

	def _fix_series_name(self, study: _FitImageStudyInfo):
		save_to = Path(f"download/{self._study_id}")
		for s in save_to.iterdir():
			desc, size = study.series[s.name]
			s.rename(s.with_name(desc))

		return save_to.rename(suggest_save_dir(study.patient, study.kind, study.time))

	async def _do_run(self, context: BrowserContext):
		page = await context.new_page()

		await page.goto(self.share_url, wait_until="commit")
		study = await wait_study_info(page)
		print(f"{study.patient}，{len(study.series)} 个序列，共 {study.total} 张图。")

		# tqdm 不能多个进度条同时动，虽然这个站是顺序下载，但异步过程还是不可依靠。
		self._total = study.total
		self._progress = tqdm(total=study.total, initial=self._downloaded, unit="张", file=sys.stdout)

		# 下得比这里跑得还快，应该不可能，但还是检查下更完备些。
		if self._downloaded >= study.total:
			await context.close()
		else:
			await context.wait_for_event("close", timeout=0)

		self._progress.close()
		print(f"下载完成，保存位置 {self._fix_series_name(study)}")


async def run(share_url, *_):
	await run_with_browser(FitImageDownloader(share_url))
