"""
下载海纳医信 miShare（*.medicalimagecloud.com） 上面的云影像，爬虫流程见：
https://blog.kaciras.com/article/45/download-dicom-files-from-hinacom-cloud-viewer
"""
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

from aiohttp import ClientSession
from pydicom.datadict import DicomDictionary
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.encaps import encapsulate
from pydicom.tag import Tag
from pydicom.uid import ExplicitVRLittleEndian, JPEG2000Lossless
from pydicom.valuerep import VR, STR_VR, INT_VR, FLOAT_VR
from tqdm import tqdm

from crawlers._utils import pathify, new_http_client

_LINK_VIEW = re.compile(r"/Study/ViewImage\?studyId=([\w-]+)")
_LINK_ENTRY = re.compile(r"window\.location\.href = '([^']+)'")
_TARGET_PATH = re.compile(r'var TARGET_PATH = "([^"]+)"')
_VAR_RE = re.compile(r'var (STUDY_ID|ACCESSION_NUMBER|STUDY_EXAM_UID|LOAD_IMAGE_CACHE_KEY) = "([^"]+)"')

async def get_viewer_url(share_url, password):
	print(f"下载海纳医信 DICOM，报告 ID：{share_url.split('/')[-1]}，密码：{password}")

	async with new_http_client() as client:
		# 先是入口页面，它会重定向到登录页并设置一个 Cookie
		async with client.get(share_url) as response:
			url = response.real_url
			uuid = url.path.split("/")[-1]

		# 登录报告页，成功后又会拿到 Cookies，从中找查看影像的链接。
		_headers = {"content-type": "application/x-www-form-urlencoded"}
		async with client.post(url, data=f"id={uuid}&Password={password}", headers=_headers) as response:
			html = await response.text()
			match = _LINK_VIEW.search(html)
			if not match:
				raise Exception("链接不存在，可能被取消分享了。")

			return str(url.origin()) + match.group(0)


async def create_downloader(viewer_url):
	client = new_http_client()

	# 访问查影像的链接。
	async with client.get(viewer_url) as response:
		html2 = await response.text()
		matches = _LINK_ENTRY.search(html2)

	# 中间不知道为什么又要跳转一次，端口还变了。
	async with client.get(matches.group(1)) as response:
		html3 = await response.text("utf-8")
		client._base_url = response.real_url.origin()
		matches = _TARGET_PATH.search(html3)

	# 查看器页，关键信息就写在 JS 里。
	async with client.get(matches.group(1)) as response:
		html4 = await response.text()
		matches = _VAR_RE.findall(html4)
		top_study_id = matches[0][1]
		accession_number = matches[1][1]
		exam_uid = matches[2][1]
		cache_key = matches[3][1]

	params = {
		"studyId": top_study_id,
		"accessionNumber": accession_number,
		"examuid": exam_uid,
		"minThickness": "5"
	}
	async with client.get("/ImageViewer/GetImageSet", params=params) as response:
		image_set = await response.json()

	return _HinacomDownloader(client, cache_key, image_set)


class _HinacomDownloader:
	client: ClientSession
	cache_key: str
	dataset: dict[str, Any]

	def __init__(self, client, cache_key, dataset):
		self.client = client
		self.cache_key = cache_key
		self.dataset = dataset
		self.refreshing = asyncio.create_task(self._refresh_cac())

	async def __aenter__(self):
		return self

	def __aexit__(self, *ignore):
		self.refreshing.cancel()
		return self.client.close()

	async def _refresh_cac(self):
		"""每一分钟要刷新一下 CAC_AUTH 令牌，另外 PY 没有尾递归优化所以还是用循环"""
		while True:
			await asyncio.sleep(60)
			(await self.client.get("/ImageViewer/renewcacauth")).close()

	async def get_tags(self, info):
		api = "/ImageViewer/GetImageDicomTags"
		params = {
			"studyId": info['studyId'],
			"imageId": info['imageId'],
			"frame": "0",
			"storageNodes": "",
		}
		async with self.client.get(api, params=params) as response:
			return await response.json()

	async def get_image(self, info, raw: bool):
		s, i, ck = info['studyId'], info['imageId'], self.cache_key
		if raw:
			api = f"/imageservice/api/image/dicom/{s}/{i}/0/0"
		else:
			api = f"/imageservice/api/image/j2k/{s}/{i}/0/3"

		async with self.client.get(api, params={"ck": ck}) as response:
			return await response.read(), response.headers["X-ImageFrame"]


def _get_save_dir(image_set):
	patient = image_set["patientName"]
	exam = image_set["studyDescription"]
	date = image_set["studyDate"]
	return Path(f"download/{patient}-{exam}-{date}")


def _cast_value_type(value: str, vr: str):
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


def _write_dicom(tag_list, image, filename):
	ds = Dataset()
	ds.file_meta = FileMetaDataset()

	# GetImageDicomTags 的响应不含 VR，故私有标签只能假设为 LO 类型。
	for item in tag_list:
		tag = Tag(item["tag"].split(",", 2))
		definition = DicomDictionary.get(tag)

		if definition:
			vr, key = definition[0], definition[4]
			setattr(ds, key, _cast_value_type(item["value"], vr))
		else:
			# 正好 PrivateCreator 出现在它的标签之前，按顺序添加即可。
			ds.add_new(tag, "LO", item["value"])

	ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
	ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID

	# 根据文件体积和头部自动判断类型。
	px_size = (ds.BitsAllocated + 7) // 8 * ds.Rows * ds.Columns
	if image[16:23] == b"ftypjp2" and len(image) != px_size:
		ds.PixelData = encapsulate([image])
		ds.file_meta.TransferSyntaxUID = JPEG2000Lossless
	else:
		ds.PixelData = image
		ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

	ds.save_as(filename, enforce_file_format=True)


async def run(report_url, password, *args):
	viewer_url = await get_viewer_url(report_url, password)
	is_raw = "--raw" in args

	async with await create_downloader(viewer_url) as downloader:
		save_to = _get_save_dir(downloader.dataset)
		print(f'保存到: {save_to}')

		for series in downloader.dataset["displaySets"]:
			name, images = pathify(series["description"]), series["images"]
			dir_ = save_to / name

			for i, info in enumerate(tqdm(images, desc=name, unit="张", file=sys.stdout)):
				# 图片响应头包含的标签不够，必须每个都请求 GetImageDicomTags。
				tags = await downloader.get_tags(info)

				# 没有标签的视为非 DCM 文件，跳过。
				if len(tags) == 0:
					continue

				pixels, _ = await downloader.get_image(info, is_raw)
				dir_.mkdir(parents=True, exist_ok=True)
				_write_dicom(tags, pixels, dir_ / f"{i}.dcm")


# ============================== 下面仅调试用 ==============================

TEMP_DIR = Path("download/dicom_temp")


async def download_debug(report_url, password, *args):
	viewer_url = await get_viewer_url(report_url, password)
	is_raw = "--raw" in args
	TEMP_DIR.mkdir(parents=True, exist_ok=True)

	async with await create_downloader(viewer_url) as downloader:
		TEMP_DIR.joinpath("ImageSet.json").write_text(json.dumps(downloader.dataset))

		for series in downloader.dataset["displaySets"]:
			name, images = series["description"].rstrip(), series["images"]
			dir_ = TEMP_DIR / name
			dir_.mkdir(exist_ok=True)

			for i, info in enumerate(tqdm(images, desc=name, unit="张", file=sys.stdout)):
				tags = await downloader.get_tags(info)
				pixels, attrs = await downloader.get_image(info, is_raw)
				dir_.joinpath(f"{i}-tags.json").write_text(json.dumps(tags))
				dir_.joinpath(f"{i}.json").write_text(attrs)
				dir_.joinpath(f"{i}.slice").write_bytes(pixels)


def build_dicom_files():
	"""读取所有临时文件夹的数据，生成跟正常下载一样的 DCM 文件"""
	with TEMP_DIR.joinpath("ImageSet.json").open() as fp:
		image_set = json.load(fp)
		name_map = {s["description"].rstrip(): s for s in image_set["displaySets"]}
		save_dir = _get_save_dir(image_set)

	for series_dir in TEMP_DIR.iterdir():
		if series_dir.is_file():
			continue
		info = name_map[series_dir.name]
		out_dir = save_dir / pathify(series_dir.name)
		out_dir.mkdir(parents=True, exist_ok=True)

		for i in range(len(info["images"])):
			tags = series_dir.joinpath(f"{i}-tags.json").read_text("utf8")
			if tags == "[]":
				continue
			pixels = series_dir.joinpath(f"{i}.slice").read_bytes()
			_write_dicom(json.loads(tags), pixels, out_dir / f"{i}.dcm")


def diff_tags(pivot, another):
	pivot = json.loads(Path(pivot).read_text("utf8"))
	another = json.loads(Path(another).read_text("utf8"))

	tag_map = {}
	for item in pivot:
		tag_map[item["tag"]] = item["value"]

	for item in another:
		if tag_map[item["tag"]] != item["value"]:
			print(f"{item['tag']} {item['name']}: {item['value']}")


if __name__ == '__main__':
	# asyncio.run(download_debug(*sys.argv[1:]))
	# diff_tags(r"C:\Users\Kaciras\Desktop\a.json", r"C:\Users\Kaciras\Desktop\b.json")
	build_dicom_files()
