import sys

from playwright.async_api import Frame, Page, ElementHandle, Playwright, Browser, Error


async def launch_browser(playwright: Playwright) -> Browser:
	driver, path = "", None

	for argument in sys.argv:
		if argument.startswith("--browser="):
			driver, path = argument[10:].split(":", 1)

	if path:
		return await getattr(playwright, driver).launch(executable_path=path)

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

