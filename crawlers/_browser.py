import asyncio
import asyncio
import sys
from typing import Any

from playwright.async_api import Frame, Page, ElementHandle, Playwright, Browser, Error, BrowserContext, WebSocket, \
	Response, async_playwright

_driver_instance: Any = None
_playwright: Playwright
_browser: Browser


async def launch_browser(playwright: Playwright) -> Browser:
	"""
	考虑到 Playwright 的支持成熟度，还是尽可能地选择 chromium 系浏览器。
	"""
	try:
		return await playwright.chromium.launch()
	except Error as e:
		if not e.message.startswith("BrowserType.launch: Executable doesn't exist"):
			raise

	if sys.platform == "win32":
		print("PlayWright: 使用 Windows 自带的 Edge 浏览器。")
		return await playwright.chromium.launch(
			executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

	raise Exception("在该系统上运行必须提供浏览器的路径。")


async def wait_text(context: Page | Frame | ElementHandle, selector: str):
	"""
	等待匹配指定选择器的元素出现，并读取其 textContent 属性。
	最好使用 wait_for_selector 而不是 query_selector，以确保元素已插入。

	:param context: 搜索范围，可以是页面或某个元素。
	:param selector: CSS 选择器
	"""
	return await (await context.wait_for_selector(selector)).text_content()


class PlaywrightCrawler:
	"""本项目的爬虫都比较简单，有固定的模式，所以写个抽象类来统一下代码"""

	_autoclose_waiter = asyncio.Event()
	_context: BrowserContext = None

	def _prepare_page(self, page: Page):
		page.on("websocket", self._on_websocket)
		page.on("close", self._check_all_closed)

	# 关闭窗口并不结束浏览器进程，只能依靠页面计数来判断。
	# https://github.com/microsoft/playwright/issues/2946
	def _check_all_closed(self, _):
		if len(self._context.pages) == 0:
			self._autoclose_waiter.set()

	def _on_response(self, response: Response):
		pass

	def _on_websocket(self, ws: WebSocket):
		pass    

	def _do_run(self, context: BrowserContext):
		pass

	def run(self, context: BrowserContext):
		self._context = context
		context.on("page", self._prepare_page)
		context.on("response", self._on_response)
		return self._do_run(context)


async def run_with_browser(crawler: PlaywrightCrawler, **kwargs):
	"""
	启动 Playwright 浏览器的快捷函数，单个 Browser 实例创建新的 Context。

	因为这库有四层（ContextManager，Playwright，Browser，BrowserContext）
	每次启动都要嵌套好几个 with 很烦，所以搞了一个全局的实例并支持自动销毁。

	:param crawler:
	:param kwargs: 转发到 Browser.new_context() 的参数
	"""
	global _browser, _playwright, _driver_instance

	if not _driver_instance:
		_driver_instance = async_playwright()
		_playwright = await _driver_instance.__aenter__()
		_browser = await launch_browser(_playwright)

	try:
		async with await _browser.new_context(**kwargs) as context:
			return crawler.run(context)
	finally:
		if len(_browser.contexts) == 0:
			await _browser.close()
			await _driver_instance.__aexit__()
