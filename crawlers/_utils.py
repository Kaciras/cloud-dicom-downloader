import re
import sys
from io import TextIOWrapper
from zipfile import ZipFile

import aiohttp

_HEADERS = {
	"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
	"Accept-Language": "zh,zh-CN;q=0.7,en;q=0.3",
	"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
}


# noinspection PyTypeChecker
async def _dump_response_check(response: aiohttp.ClientResponse):
	if response.ok:
		return

	with ZipFile('dump.zip', 'w') as pack:
		a, b = response.version

		with TextIOWrapper(pack.open("request.headers", "w")) as fp:
			fp.write(f"{response.method} {response.url.path_qs} HTTP{a}/{b}")
			for k, v in response.request_info.headers.items():
				fp.write(f"\r\n{k}: {v}")

		with pack.open("response.headers", "w") as fp:
			a = f"HTTP{a}/{b} {response.status} {response.reason}"
			fp.write(a.encode())

			for k, v in response.raw_headers:
				fp.write(b"\r\n" + k + b": " + v)

		with pack.open("response.body", "w") as fp:
			async for chunk in response.content.iter_chunked(16384):
				fp.write(chunk)

	print("响应已转储到 dump.zip", file=sys.stderr)

	response.raise_for_status()  # 继续 aiohttp 内置的处理，让调用端保持一致。


def new_http_client(*args, **kwargs):
	kwargs.setdefault("raise_for_status", _dump_response_check)
	kwargs.setdefault("headers", _HEADERS)
	return aiohttp.ClientSession(*args, **kwargs)


_illegal_path_chars = re.compile(r'[<>:"/\\?*|]')


def _to_full_width(match: re.Match[str]):
	if match[0] == ":": return "："
	if match[0] == "*": return "＊"
	if match[0] == "?": return "？"
	if match[0] == '"': return "'"
	if match[0] == '|': return "｜"
	if match[0] == '<': return "＜"
	if match[0] == '>': return "＞"
	if match[0] == "/": return "／"
	if match[0] == "\\": return "＼"


def pathify(text: str):
	"""
	为了用户易读，推荐使用影像的刻度名字作为目录名，但影像名可以有任意字符，而某些是文件名不允许的。
	这里就把非法字符替换为 Unicode 的宽字符，虽然有点别扭但并不损失易读性。
	"""
	return _illegal_path_chars.sub(_to_full_width, text.strip())
