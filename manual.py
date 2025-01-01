import asyncio
import io
from dataclasses import dataclass
from io import TextIOWrapper
from pathlib import Path

from playwright.async_api import Playwright, Response
from yarl import URL

index = 0

_DUMP_FILE_COMMENT = "# HTTP dump file, request body size = "


async def dump(directory: Path, response: Response):
	global index
	index += 1
	request = response.request

	if request.post_data_buffer:
		req_body_size = len(request.post_data_buffer)
	else:
		req_body_size = 0

	with directory.joinpath(F"{index}.http").open("wb") as fp:
		writer = TextIOWrapper(fp, encoding="utf-8", newline="", write_through=True)
		writer.write(F"{_DUMP_FILE_COMMENT}{req_body_size}\r\n")

		# 这里第一行直接用了 URL 而非标准中的 Path
		writer.write(f"{request.method} {request.url} HTTP1/1")
		for k, v in (await request.all_headers()).items():
			writer.write(f"\r\n{k}: {v}")

		fp.write(b"\r\n\r\n")
		writer.write(f"HTTP1/1 {response.status} {response.status_text}")
		for k, v in response.headers.items():
			writer.write(f"\r\n{k}:{v}")

		fp.write(b"\r\n\r\n")
		if request.post_data_buffer:
			fp.write(request.post_data_buffer)

		fp.write(await response.body())


@dataclass(eq=False, slots=True)
class HTTPNetworkDumpFile:
	"""

	"""

	_headers_end: int
	_request_body_size: int

	file: Path

	method: str
	url: URL
	request_headers: dict[str, str]

	status: int
	response_headers: dict[str, str]

	def request_body(self) -> bytes:
		with self.file.open("rb") as fp:
			fp.seek(self._headers_end)
			return fp.read(self._request_body_size)

	def response_body(self) -> bytes:
		skip = self._headers_end + self._request_body_size
		with self.file.open("rb") as fp:
			fp.seek(skip)
			return fp.read()


def deserialize(dump_file: Path):
	with dump_file.open("rb") as fp:
		reader = io.TextIOWrapper(fp, encoding="utf-8", newline="\r\n")
		qbs = int(reader.readline().rstrip("\r\n")[len(_DUMP_FILE_COMMENT):])

		m, u, _ = reader.readline().rstrip("\r\n").split(" ", 2)
		qh: dict[str, str] = {}
		while True:
			header = reader.readline().rstrip("\r\n")
			if not header:
				break
			k, v = header.split(":", 1)
			qh[k] = v

		_, s, reason = reader.readline().rstrip("\r\n").split(" ", 2)
		rh: dict[str, str] = {}
		while True:
			header = reader.readline().rstrip("\r\n")
			if not header:
				break
			k, v = header.split(":", 1)
			rh[k] = v

		# 不能用 fp.tell 因为 TextIOWrapper 有缓冲，正好除请求体外都是文本。
		ho = reader.tell()

	return HTTPNetworkDumpFile(ho, qbs, dump_file, m, URL(u), qh, int(s), rh)


async def run(playwright: Playwright):
	chromium = playwright.chromium  # or "firefox" or "webkit".
	browser = await chromium.launch(
		executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
		headless=False,
	)
	page = await browser.new_page()
	page.context.on("response", intercept)
	await page.goto("https://tieba.baidu.com/index.html")
	# other actions...
	await browser.close()


async def intercept(response: Response):
	await dump(Path("exports"), response)


async def main():
	# async with async_playwright() as playwright:
	# 	await run(playwright)

	gg = deserialize(Path("exports/2.http"))
	print(gg.response_body())


Path("exports").mkdir(exist_ok=True)
asyncio.run(main())
