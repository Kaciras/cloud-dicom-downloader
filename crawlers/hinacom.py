import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import aiohttp
from pydicom.datadict import DicomDictionary
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.encaps import encapsulate
from pydicom.tag import Tag
from pydicom.uid import ExplicitVRLittleEndian, JPEG2000Lossless
from pydicom.valuerep import VR, STR_VR, INT_VR, FLOAT_VR
from tqdm import tqdm

# 保存位置
SAVE_DIR = Path("download/dicom")
# 保存中间输出，仅调试用
TEMP_DIR = Path("download/dicom_temp")

# ============================================================

_HEADERS = {
	"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
	"Accept-Language": "zh,zh-CN;q=0.7,en;q=0.3",
	"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
}

_LINK_VIEW = re.compile(r"/Study/ViewImage\?studyId=([\w-]+)")
_LINK_ENTRY = re.compile(r"window\.location\.href = '([^']+)'")
_TARGET_PATH = re.compile(r'var TARGET_PATH = "([^"]+)"')
_VAR_RE = re.compile(r'var (STUDY_ID|ACCESSION_NUMBER|STUDY_EXAM_UID|LOAD_IMAGE_CACHE_KEY) = "([^"]+)"')

_REFRESH_CAC = timedelta(minutes=1)


async def get_viewer_url(share_url, password):
	print(f"下载海纳医信 DICOM，报告 ID：{share_url.split('/')[-1]}，密码：{password}")

	async with aiohttp.ClientSession(headers=_HEADERS, raise_for_status=True) as client:
		# 先是入口页面，它会重定向到登录页并设置一个 Cookie
		async with client.get(share_url) as response:
			url = response.real_url
			origin = str(url.origin())
			uuid = url.path.split("/")[-1]

		# 登录报告页，成功后又会拿到 Cookies，从中找查看影像的链接。
		_headers = {"content-type": "application/x-www-form-urlencoded"}
		async with client.post(url, data=f"id={uuid}&Password={password}", headers=_headers) as response:
			html = await response.text()
			return origin + _LINK_VIEW.search(html).group(0)


async def run(viewer_url, password, *args):
	viewer_url = await get_viewer_url(viewer_url, password)

	if "--j2k" in args:
		image_service = "/imageservice/api/image/j2k/{}/{}/0/3"
	else:
		image_service = "/imageservice/api/image/dicom/{}/{}/0/0"

	async with aiohttp.ClientSession(headers=_HEADERS, raise_for_status=True) as client:
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
			print(f'姓名：{image_set["patientName"]}')
			print(f'检查：{image_set["studyDescription"]}')
			print(f'日期：{image_set["studyDate"]}\n')

			file = TEMP_DIR / "DataSet.json"
			file.parent.mkdir(parents=True, exist_ok=True)
			file.write_text(json.dumps(image_set))

		for series in image_set["displaySets"]:
			await _download_series(client, series, image_service, cache_key)


async def _download_series(client, series, image_service, ck):
	name, images = series["description"].rstrip(), series["images"]
	login_time = datetime.now()
	dir_ = TEMP_DIR / name

	for i, info in enumerate(tqdm(images, desc=name, unit="张", file=sys.stdout)):
		study_id, image_id = info['studyId'], info['imageId']

		# 图片响应头包含的标签不够，必须每个都请求 GetImageDicomTags。
		params = {
			"studyId": study_id,
			"imageId": image_id,
			"frame": "0",
			"storageNodes": "",
		}
		async with client.get("/ImageViewer/GetImageDicomTags", params=params) as response:
			tags = await response.read()
			if tags == b"[]":  # 患者方案不知道是啥，没有标签，不下载了。
				return
			if i == 0:
				dir_.mkdir()
			dir_.joinpath(f"{i}.json").write_bytes(tags)

		image_url = image_service.format(study_id, image_id)
		async with client.get(image_url, params={"ck": ck}) as response:
			pixels = await response.read()
			dir_.joinpath(f"{i}.slice").write_bytes(pixels)

		# 每一分钟要刷新一下 CAC_AUTH 令牌
		if datetime.now() - login_time >= _REFRESH_CAC:
			(await client.get("/ImageViewer/renewcacauth")).close()
			login_time = datetime.now()


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


def _write_dicom(tags, pixels, file):
	ds = Dataset()
	ds.file_meta = FileMetaDataset()

	# 这里认为 tags 中除 metadata 外的都是 Series 共有的。
	for item in tags:
		group, element = item["tag"].split(",")
		id_ = (int(group, 16) << 16) | int(element, 16)
		definition = DicomDictionary.get(id_)

		# /GetImageDicomTags 的响应不含 VR，故私有标签只能假设为 LO 类型。
		if definition:
			vr, key = definition[0], definition[4]
			setattr(ds, key, _cast_value_type(item["value"], vr))
		else:
			group, element = item["tag"].split(",")
			ds.add_new(Tag(group, element), "LO", item["value"])

	ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
	ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID

	if "--j2k" in sys.argv[1:]:
		ds.file_meta.TransferSyntaxUID = JPEG2000Lossless
		ds.PixelData = encapsulate([pixels])
	else:
		ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
		ds.PixelData = pixels

	# print(str(ds))
	ds.save_as(file, enforce_file_format=True)


def build_dicom_files():
	"""调试用，读取所有临时文件夹的数据，生成跟正常下载一样的 DCM 文件"""
	with TEMP_DIR.joinpath("DataSet.json").open() as fp:
		studies = json.load(fp)
		name_map = {s["description"].rstrip(): s for s in studies["displaySets"]}

	for series_dir in TEMP_DIR.iterdir():
		if series_dir.is_file():
			continue
		info = name_map[series_dir.name]
		out_dir = SAVE_DIR / series_dir.name
		out_dir.mkdir(parents=True, exist_ok=True)

		for i in range(len(info["images"])):
			tags = series_dir.joinpath(f"{i}.json").read_text("utf8")
			pixels = series_dir.joinpath(f"{i}.slice").read_bytes()
			_write_dicom(json.loads(tags), pixels, out_dir / f"{i}.dcm")


def diff_tags(pivot, another, frame_attrs):
	pivot = json.loads(Path(pivot).read_text("utf8"))
	another = json.loads(Path(another).read_text("utf8"))
	fa = json.loads(Path(frame_attrs).read_text("utf8"))

	tag_map = {}
	for item in pivot:
		tag_map[item["tag"]] = item["value"]

	for item in another:
		if tag_map[item["tag"]] != item["value"]:
			print(f"{item['tag']} {item['name']}: {item['value']}")


if __name__ == '__main__':
	# asyncio.run(run())
	build_dicom_files()
	# diff_tags(r"C:\Users\Kaciras\Desktop\a.json", r"C:\Users\Kaciras\Desktop\b.json")
