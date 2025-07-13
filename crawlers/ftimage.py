import asyncio
import os
import re
from pathlib import Path

from playwright.async_api import Playwright, Response, async_playwright
from yarl import URL


async def x(playwright: Playwright, url: str):
	browser = await playwright.chromium.launch(
		headless=False,
		executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
	)

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
	await waiter.wait()
	await browser.close(reason="Close as completed.")


_downloaded_count = 0
_total_files = 0
_desc_re = re.compile(r"\d+\^(.+)")  # 052006^肺部CT
_study_id = None
_info = None


async def dump_http(response: Response):
	"""
	将响应和它的请求序列化到同一个文件，该文件虽以 .http 结尾但并不是标准的格式。
	这样的设计是文件可以直接以文本的形式的浏览，如果用 zip 的话还要多打开一次。
	"""
	global _downloaded_count, _total_files, _study_id, _info

	url = URL(response.request.url).path
	if not url.endswith(".dcm"):
		return
	_, _, _, _study_id, series_id, _, name = url.split("/")

	dir_ = Path(f"download/{_study_id}/{series_id}/{name}")
	dir_.parent.mkdir(parents=True, exist_ok=True)
	dir_.write_bytes(await response.body())

	_downloaded_count += 1

	if _total_files == 0:
		_info: dict = await response.frame.evaluate(_js_code)
		print(_info)
		for _, count in _info.values():
			_total_files += int(_RE_SERIES_SIZE.match(count).group(1))

	if _downloaded_count == _total_files:
		print("<UNK>")


# 玩不明白 Playwright 的选择器，还是改用 JS 来解析网页内容。
_js_code = """function () {
	const items = document.querySelectorAll("li[data-seriesuuid]");
	const seriesTable = {};
	for (const item of items) {
		const id = item.getAttribute("data-seriesuuid");
		const desc = item.querySelector(".desc");
		const [a, b] = desc.children;
		seriesTable[id] = [a.textContent, b.textContent];
	}
	const patient = document.querySelector(".info > .name").textContent;
	const description = document.querySelector(".report-list > dd").textContent;
	return { seriesTable, patient, description };
}"""

_RE_STUDY_SIZE = re.compile("序列:\s(\d+)\s影像:\s(\d+)")
_RE_SERIES_SIZE = re.compile(r"共 (\d+)张")  # 共 65张


async def run(share_url):
	async with async_playwright() as playwright:
		await x(playwright, share_url)

	for s in Path(f"download/{_study_id}").iterdir():
		slices = os.listdir(s)
		for slice in slices:
			pass

		real_name = _info[s.name][0]
		s.rename(s.with_name(real_name))
