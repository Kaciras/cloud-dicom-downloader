import math
import random
import re
import sys
from base64 import b64encode
from hashlib import sha256
from io import TextIOWrapper
from pathlib import Path
from zipfile import ZipFile

import aiohttp
from pydicom import Dataset
from pydicom.tag import Tag
from pydicom.valuerep import VR, STR_VR, INT_VR, FLOAT_VR

_UA_VER = random.randint(109, 134)

_HEADERS = {
	"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
	"Accept-Language": "zh,zh-CN;q=0.7,en;q=0.3",
	"Upgrade-Insecure-Requests": "1",
	"User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:{_UA_VER}.0) Gecko/20100101 Firefox/{_UA_VER}.0",
}


# noinspection PyTypeChecker
async def _dump_response_check(response: aiohttp.ClientResponse):
	"""
	检查响应码，如果大于等于 400 则转储该响应的数据到一个压缩包，并抛出异常。
	"""
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
	headers = kwargs.get("headers")
	kwargs.setdefault("raise_for_status", _dump_response_check)
	if headers:
		kwargs["headers"] = _HEADERS | headers
	else:
		kwargs["headers"] = _HEADERS

	return aiohttp.ClientSession(*args, **kwargs)


_illegal_path_chars = re.compile(r'[<>:"/\\?*|]')


def _to_full_width(match: re.Match[str]):
	# 一堆 if 用时 2.54s，跟从 dict 取用时 2.23s 差不多。
	char = match[0]
	if char == ":": return "："
	if char == "*": return "＊"
	if char == "?": return "？"
	if char == '"': return "'"
	if char == '|': return "｜"
	if char == '<': return "＜"
	if char == '>': return "＞"
	if char == "/": return "／"
	if char == "\\": return "＼"


def pathify(text: str):
	"""
	为了易读，使用影像的显示名作为目录名，但它可以有任意字符，而某些是文件名不允许的。
	这里把非法符号替换为 Unicode 的宽字符，虽然有点别扭但并不损失易读性。
	"""
	return _illegal_path_chars.sub(_to_full_width, text.strip())


_filename_serial_re = re.compile(r"^(.+?) \((\d+)\)$")


def make_unique_dir(path: Path):
	"""
	创建一个新的文件夹，如果指定的名字已存在则在后面添加数字使其唯一。
	实际中发现一些序列的名字相同，使用此方法可确保不覆盖。

	:param path: 原始路径
	:return: 新建的文件夹的路径，可能不等于原始路径
	"""
	try:
		path.mkdir(parents=True, exist_ok=False)
		return path
	except OSError:
		if not path.is_dir():
			raise
		matches = _filename_serial_re.match(path.stem)
		if matches:
			n = int(matches.group(2)) + 1
			alt = f"{matches.group(1)} ({n})"
		else:
			alt = f"{path.stem} (1)"

		alt += path.suffix
		return make_unique_dir(path.parent / alt)


class SeriesDirectory:
	"""
	封装了创建序列文件夹，以及计算影像文件名的操作，做了一些特殊处理：

	- 防止序列目录名重复，自动添加编号后缀。
	- 延迟创建目录，直到获取文件名准备写入。
	- 映像文件名填充 0 前缀，确保列出文件操作能返回正确的顺序。
	"""

	def __init__(self, path: Path, size: int, unique=True):
		self._suggested = path
		self._unique = unique
		self._path = None
		self._width = int(math.log10(size)) + 2

	def make_dir(self):
		if self._unique:
			self._path = make_unique_dir(self._suggested)
		else:
			self._path = self._suggested
			self._path.mkdir(exist_ok=True)

	def get(self, index: int, extension: str) -> Path:
		"""
		获取指定次序图片的文件名，并自动创建父目录。

		之所以使用该方法，是因为文件系统遍历目录的顺序是不确定的，最常见的情况就是按照字符顺序，
		以至于出现 "2.dcm" > "12.dcm"，而该方法会在前面填 "0" 来避免该情况。

		:param index: 图像的次序
		:param extension: 文件扩展名
		:return: 文件路径，一般接下来就是写入文件。
		"""
		if not self._path:
			self.make_dir()
		base = f"{index + 1}.{extension}"
		width = self._width + len(extension)
		return self._path / base.zfill(width)


def parse_dcm_value(value: str, vr: str):
	"""
	在 pydicom 里没找到自动转换的功能，得自己处理下类型。
	https://stackoverflow.com/a/77661160/7065321
	"""
	if vr == VR.AT:
		return Tag(value)

	if vr in STR_VR:
		cast_fn = str
	elif vr in INT_VR or vr == "US or SS":
		cast_fn = int
	elif vr in FLOAT_VR:
		cast_fn = float
	else:
		raise NotImplementedError("Unsupported VR: " + vr)

	parts = value.split("\\")
	if len(parts) == 1:
		return cast_fn(value)
	return [cast_fn(x) for x in parts]


def suggest_series_name(ds: Dataset):
	"""
	从实例的标签中获取序列名，不一定存在所以有时也得考虑从外层获取。
	"""
	if ds.SeriesDescription:
		return ds.SeriesDescription
	if ds.SeriesNumber is not None:
		return str(ds.SeriesNumber)
	if ds.SeriesInstanceUID:
		h = sha256(ds.SeriesInstanceUID)
		h = h.digest()
		return b64encode(h)[:20].decode()
