import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl

from pydicom.datadict import DicomDictionary
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.encaps import encapsulate
from pydicom.tag import Tag
from pydicom.uid import ExplicitVRLittleEndian, JPEG2000Lossless
from tqdm import tqdm
from yarl import URL

from crawlers._utils import pathify, new_http_client, parse_dcm_value
from crawlers.hinacom import create_downloader_1

_TARGET_URL = re.compile(r'var TARGET_URL = "([^"]+)"')


async def run(share_url, *args):
	is_raw = "--raw" in args

	parsed = URL(share_url)
	print(f"下载海纳医信 DICOM（重庆卫建委），分享 ID：{share_url.split('/')[-1]}")

	ss = share_url[share_url.rfind("?")+1:]
	query = dict(parse_qsl(ss))

	client = new_http_client()

	# 先是入口页面，它会重定向到登录页并设置一个 SF_cookie_15
	(await client.get(share_url)).close()

	# 拿 hospital_code 和 study_primary_id
	async with client.post(
			"https://mdmis.cq12320.cn/wcs1/mdmis-app/h5/api/share/check/time",
			json={
				"content": query["content"],
				"share_id": query["share_id"]
			}) as response:
		body = await response.json()
		if body["code"] != 200:
			raise Exception("xxxxx1")

		extend = json.loads(body["data"]["extend"])
		study_id, hospital_code = extend["study_primary_id"], extend["hospital_code"]

	print("hospital_code: " + hospital_code)
	print("study_primary_id: " + study_id)

	# 拿 ZFP_SessionId, ZFPXAUTH，注意这里自动重定向了一次。
	async with client.get(f"https://mdmis.cq12320.cn/wcs1/mdmis-app/h5/api/qinming_h5/api/ch/report/PacsEntry.aspx?hospitalCode={hospital_code}&studyPrimaryId={study_id}") as response:
		html2 = await response.text()
		matches = _TARGET_URL.search(html2)
		vurl = str(response.real_url.origin()) + matches.group(1)

	async with await create_downloader_1(vurl, client) as downloader:
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


def _get_save_dir(image_set):
	exam = pathify(image_set["studyDescription"])
	date = image_set["studyDate"]
	patient = pathify(image_set["patientName"])
	return Path(f"download/{patient}-{exam}-{date}")


def _write_dicom(tag_list, image, filename):
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
