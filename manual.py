import asyncio
import shutil
from dataclasses import dataclass
from io import TextIOWrapper
from pathlib import Path
from typing import BinaryIO

from playwright.async_api import Playwright, Response, async_playwright, BrowserContext, WebSocket
from yarl import URL

_DUMP_FILE_STORE = Path("download/dumps")
_DUMP_FILE_COMMENT = "# HTTP dump file, request body size = "

index = 0

async def dump_websocket(ws: WebSocket):
	global index
	index += 1

	fp = _DUMP_FILE_STORE.joinpath(F"{index}.ws").open("wb")

	def write_data(method, data: str | bytes):
		fp.write(method)
		if isinstance(data, bytes):
			fp.write(F":bytes:{len(data)}\n".encode())
			fp.write(data)
		else:
			fp.write(F":str:{len(data)}\n".encode())
			fp.write(data.encode())
		fp.write(b"\n\n")

	def handle_sent(data: str | bytes):
		write_data(b"sent", data)

	def handle_received(data: str | bytes):
		write_data(b"received", data)

	def ccc(_):
		fp.close()
		print("websocket closing...")

	ws.on("close",ccc)
	ws.on("framesent", handle_sent)
	ws.on("framereceived", handle_received)


async def dump_http(response: Response):
	global index
	index += 1
	request = response.request

	if request.post_data_buffer:
		req_body_size = len(request.post_data_buffer)
	else:
		req_body_size = 0

	with _DUMP_FILE_STORE.joinpath(F"{index}.http").open("wb") as fp:
		writer = TextIOWrapper(fp, encoding="utf-8", newline="", write_through=True)
		writer.write(F"{_DUMP_FILE_COMMENT}{req_body_size}\r\n")

		# 这里第一行直接用了 URL 而非标准中的 Path
		writer.write(f"{request.method} {request.url} HTTP1/1")

		# all_headers 返回报文层面的数据，需要滤掉 HTTP2 的特殊头。
		for k, v in (await request.all_headers()).items():
			if k[0] != ":":
				writer.write(f"\r\n{k}: {v}")

		fp.write(b"\r\n\r\n")
		writer.write(f"HTTP1/1 {response.status} {response.status_text}")
		for k, v in response.headers.items():
			writer.write(f"\r\n{k}:{v}")

		fp.write(b"\r\n\r\n")
		if request.post_data_buffer:
			fp.write(request.post_data_buffer)

		# 浏览器对 204 No Content 响应可能跳过响应体。
		if response.status == 204:
			return

		# Response body is unavailable for redirect responses
		if response.status < 300 or response.status >= 400:
			fp.write(await response.body())


def _next_line(fp: BinaryIO):
	"""
	TextIO 对 \r\n 的处理很垃圾，不自动去掉 \r，还得自己处理。
	"""
	return fp.readline()[:-2].decode("utf-8")


def _read_headers(fp: BinaryIO):
	headers = {}
	while True:
		line = _next_line(fp)
		if not line:
			return headers
		k, v = line.split(":", 1)
		headers[k] = v


@dataclass(slots=True, eq=False, repr=False)
class HTTPDumpFile:
	"""
	转储的 HTTP 文件，在同一个文件里同时包含了请求和响应。
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

	@staticmethod
	def read_from(dump_file: Path):
		with dump_file.open("rb") as fp:
			request_body_size = int(_next_line(fp)[len(_DUMP_FILE_COMMENT):])

			method, url, _ = _next_line(fp).split(" ", 2)
			request_headers = _read_headers(fp)

			_, status, reason = _next_line(fp).split(" ", 2)
			response_headers = _read_headers(fp)

			body_offset = fp.tell()

		return HTTPDumpFile(
			body_offset, request_body_size, dump_file, method,
			URL(url), request_headers, int(status), response_headers
		)


async def run(playwright: Playwright):
	browser = await playwright.chromium.launch(
		executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
		headless=False,
	)

	context = await browser.new_context()
	waiter = asyncio.Event()

	# 关闭浏览器窗口并不结束浏览器进程，只能依靠页面计数来判断。
	# https://github.com/microsoft/playwright/issues/2946
	def check_all_closed():
		if len(context.pages) == 0:
			waiter.set()

	context.on("page", lambda p: p.on("close", check_all_closed))

	page = await context.new_page()
	context.on("response", dump_http)
	page.on("websocket", dump_websocket)

	await page.goto("https://tieba.baidu.com/index.html", wait_until="commit")

	await waiter.wait()
	await browser.close()


async def dump_network():
	shutil.rmtree(_DUMP_FILE_STORE, True)
	_DUMP_FILE_STORE.mkdir(parents=True)

	async with async_playwright() as playwright:
		await run(playwright)


def deserialize_ws(dump_file: Path):
	frames = []
	with dump_file.open("rb") as fp:
		while True:
			line = fp.readline()
			if not line:
				return frames
			method, type_, size = line.split(b":")
			is_sent = method == b"sent"
			data = fp.read(int(size))
			if type_ == b"str":
				data = data.decode()
			fp.read(2)
			frames.append((is_sent, data))


async def inspect():
	for file in _DUMP_FILE_STORE.iterdir():
		if file.suffix == ".ws":
			frames = deserialize_ws(file)
			print(len(frames))
		else:
			exchange = HTTPDumpFile.read_from(file)
			if exchange.method == "POST":
				print(file)


# asyncio.run(inspect())
asyncio.run(dump_network())
