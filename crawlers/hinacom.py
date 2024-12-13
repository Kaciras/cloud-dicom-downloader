"""
下载海纳医信 miShare（*.medicalimagecloud.com） 上面的云影像，爬虫流程见：
https://blog.kaciras.com/article/45/download-dicom-files-from-hinacom-cloud-viewer
"""
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

from aiohttp import ClientSession
from pydicom.datadict import DicomDictionary
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.encaps import encapsulate
from pydicom.tag import Tag
from pydicom.uid import ExplicitVRLittleEndian, JPEG2000Lossless
from tqdm import tqdm

from crawlers._utils import pathify, new_http_client, parse_dcm_value, make_unique_dir

_LINK_VIEW = re.compile(r"/Study/ViewImage\?studyId=([\w-]+)")
_LINK_ENTRY = re.compile(r"window\.location\.href = '([^']+)'")
_TARGET_PATH = re.compile(r'var TARGET_PATH = "([^"]+)"')
_VAR_RE = re.compile(r'var (STUDY_ID|ACCESSION_NUMBER|STUDY_EXAM_UID|LOAD_IMAGE_CACHE_KEY) = "([^"]+)"')


class HinacomDownloader:
	"""
	海纳医信医疗影像系统的下载器，该系统在中国的多个地区被采用。
	"""

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
		"""每分钟要刷新一下 CAC_AUTH 令牌，因为 PY 没有尾递归优化所以还是用循环"""
		while True:
			await asyncio.sleep(60)
			(await self.client.get("ImageViewer/renewcacauth")).close()

	async def get_tags(self, info):
		api = "ImageViewer/GetImageDicomTags"
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
			api = f"imageservice/api/image/dicom/{s}/{i}/0/0"
		else:
			api = f"imageservice/api/image/j2k/{s}/{i}/0/3"

		async with self.client.get(api, params={"ck": ck}) as response:
			return await response.read(), response.headers["X-ImageFrame"]

	async def download_all(self, is_raw=False):
		"""
		快捷方法，下载全部序列到 DCM 文件，保存的文件名将根据报告自动生成。
		该方法会在控制台显示进度条和相关信息。

		:param is_raw: 是否下载未压缩的图像，默认下载 JPEG2000 格式的。
		"""
		save_to = _get_save_dir(self.dataset)
		print(f'保存到: {save_to}')

		for series in self.dataset["displaySets"]:
			name, images = pathify(series["description"]), series["images"]
			dir_: Optional[Path] = None

			tasks = tqdm(images, desc=name, unit="张", file=sys.stdout)
			for i, info in enumerate(tasks, 1):
				# 图片响应头包含的标签不够，必须每个都请求 GetImageDicomTags。
				tags = await self.get_tags(info)

				# 没有标签的视为非 DCM 文件，跳过。
				if len(tags) == 0:
					continue

				# 仅有图片时才创建目录，避免空文件夹。
				if not dir_:
					dir_ = make_unique_dir(save_to / name)

				pixels, _ = await self.get_image(info, is_raw)
				_write_dicom(tags, pixels, dir_ / f"{i}.dcm")

	@staticmethod
	async def from_url(client: ClientSession, viewer_url: str):
		"""
		从查看器页读取必要的信息，创建下载器，需要先登录并将 Cookies 保存到 client 中。

		:param client: 会话对象，要先拿到 ZFP_SessionId 和 ZFPXAUTH
		:param viewer_url: 页面 URL，路径中要有 /ImageViewer/StudyView
		"""
		async with client.get(viewer_url) as response:
			html4 = await response.text()
			matches = _VAR_RE.findall(html4)
			top_study_id = matches[0][1]
			accession_number = matches[1][1]
			exam_uid = matches[2][1]
			cache_key = matches[3][1]

			# 查看器可能被整合进了其它系统里，路径有前缀。
			origin, path = response.real_url.origin(), response.real_url.path
			offset = path.index("/ImageViewer/StudyView")
			client._base_url = origin.with_path(path[:offset + 1])

		# 获取检查的基本信息，顺便也判断下访问是否成功。
		params = {
			"studyId": top_study_id,
			"accessionNumber": accession_number,
			"examuid": exam_uid,
			"minThickness": "5"
		}
		async with client.get("ImageViewer/GetImageSet", params=params) as response:
			image_set = await response.json()

		return HinacomDownloader(client, cache_key, image_set)


def _get_save_dir(image_set):
	exam = pathify(image_set["studyDescription"])
	date = image_set["studyDate"]
	patient = pathify(image_set["patientName"])
	return Path(f"download/{patient}-{exam}-{date}")


def _write_dicom(tag_list: list, image: bytes, filename: Path):
	ds = Dataset()
	ds.file_meta = FileMetaDataset()

	# GetImageDicomTags 的响应不含 VR，故私有标签只能假设为 LO 类型。
	for item in tag_list:
		tag = Tag(item["tag"].split(",", 2))
		definition = DicomDictionary.get(tag)

		if definition:
			vr, key = definition[0], definition[4]
			setattr(ds, key, parse_dcm_value(item["value"], vr))
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


async def run(share_url, password, *args):
	print(f"下载海纳医信 DICOM，报告 ID：{share_url.split('/')[-1]}，密码：{password}")
	client = new_http_client()

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

		redirect_url = str(url.origin()) + match.group(0)

	# 访问查影像的链接。
	async with client.get(redirect_url) as response:
		html2 = await response.text()
		matches = _LINK_ENTRY.search(html2)

	# 中间不知道为什么又要跳转一次，端口还变了。
	async with client.get(matches.group(1)) as response:
		html3 = await response.text("utf-8")
		client._base_url = response.real_url.origin()
		viewer_url = _TARGET_PATH.search(html3).group(1)

	async with await HinacomDownloader.from_url(client, viewer_url) as downloader:
		await downloader.download_all("--raw" in args)


# ============================== 下面仅调试用 ==============================


async def fetch_responses(downloader: HinacomDownloader, save_to: Path, is_raw: bool):
	"""
	下载原始的响应用于调试，后续可以用 build_dcm_from_responses 组合成 DCM 文件。

	:param downloader: 下载器对象
	:param save_to: 保存的路径
	:param is_raw: 是否下载未压缩的图像，默认下载 JPEG2000 格式的。
	"""
	save_to.mkdir(parents=True, exist_ok=True)
	save_to.joinpath("ImageSet.json").write_text(json.dumps(downloader.dataset))

	for series in downloader.dataset["displaySets"]:
		name, images = pathify(series["description"]), series["images"]
		dir_ = make_unique_dir(save_to / name)

		tasks = tqdm(images, desc=name, unit="张", file=sys.stdout)
		for i, info in enumerate(tasks, 1):
			tags = await downloader.get_tags(info)
			pixels, attrs = await downloader.get_image(info, is_raw)
			dir_.joinpath(f"{i}-tags.json").write_text(json.dumps(tags))
			dir_.joinpath(f"{i}.json").write_text(attrs)
			dir_.joinpath(f"{i}.slice").write_bytes(pixels)


def build_dcm_from_responses(source_dir: Path):
	"""
	读取所有临时文件夹的数据（fetch_responses 下载的），合并成 DCM 文件。

	:param source_dir: fetch_responses 的 save_t
	"""
	with source_dir.joinpath("ImageSet.json").open() as fp:
		image_set = json.load(fp)
		name_map = {s["description"].rstrip(): s for s in image_set["displaySets"]}
		save_dir = _get_save_dir(image_set)

	for series_dir in source_dir.iterdir():
		if series_dir.is_file():
			continue
		info = name_map[series_dir.name]
		out_dir = save_dir / pathify(series_dir.name)
		out_dir.mkdir(parents=True, exist_ok=True)

		for i in range(1, len(info["images"]) + 1):
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
