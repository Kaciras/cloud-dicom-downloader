"""
下载 szjudianyun.com 上面的云影像，爬虫流程见：
https://blog.kaciras.com/article/39/download-raw-dicom-from-cloud-ct-viewer
"""
import json
import random
import re
import string
import sys
from io import BytesIO
from pathlib import Path
from typing import Optional

from aiohttp import ClientWebSocketResponse
from pydicom import dcmread, Dataset
from tqdm import tqdm
from yarl import URL

from crawlers._utils import new_http_client, SeriesDirectory, suggest_save_dir

_WHITE_SPACES = re.compile(r"\s+")

separator = "b1u2d3d4h5a"

# 常量，是一堆 DICOM 的 TAG ID，由 b1u2d3d4h5a 分隔。
tag = "0x00100010b1u2d3d4h5a0x00101001b1u2d3d4h5a0x00100020b1u2d3d4h5a0x00100030b1u2d3d4h5a0x00100040b1u2d3d4h5a0x00101010b1u2d3d4h5a0x00080020b1u2d3d4h5a0x00080030b1u2d3d4h5a0x00180015b1u2d3d4h5a0x00180050b1u2d3d4h5a0x00180088b1u2d3d4h5a0x00080080b1u2d3d4h5a0x00181100b1u2d3d4h5a0x00280030b1u2d3d4h5a0x00080060b1u2d3d4h5a0x00200032b1u2d3d4h5a0x00200037b1u2d3d4h5a0x00280030b1u2d3d4h5a0x00280010b1u2d3d4h5a0x00280011b1u2d3d4h5a0x00080008b1u2d3d4h5a0x00200013b1u2d3d4h5a0x0008103Eb1u2d3d4h5a0x00181030b1u2d3d4h5a0x00080070b1u2d3d4h5a0x00200062b1u2d3d4h5a0x00185101";

# 什么傻逼 qinniao，不会是北大青鸟吧？看上去是个小作坊外包，应该不会有更多域名了。
base_url = "http://qinniaofu.coolingesaving.com:63001"


def _send_message(ws, id_, **message):
	return ws.send_str(str(id_) + json.dumps(["sendMessage", message]))


async def _get_dcm(ws, hospital_id, study, series, instance):
	await _send_message(
		ws, 42,
		hospital_id=hospital_id,
		study=study,
		tag=tag,
		type="hangC",
		ww="",
		wl="",
		series=series,
		series_in=str(instance + 1)
	)

	# 451 开头的回复消息，没什么用。
	await anext(ws)

	# 第一位 4 是 socket.io 添加的需要跳过。
	return (await anext(ws)).data[1:]


def _get_save_dir(ds: Dataset):
	patient = _WHITE_SPACES.sub("", str(ds.PatientName).title())
	desc = ds.StudyDescription or ds.Modality
	datetime = f"{ds.StudyDate}{ds.StudyTime}".rsplit(".", 1)[0]
	return suggest_save_dir(patient, desc, datetime)


async def download_study(ws: ClientWebSocketResponse, info):
	hospital_id, study = info["hosipital"].split(separator, 2)
	series_list, sizes = info["series"], info["series_dicom_number"]

	study_dir: Optional[Path] = None

	for sid in series_list:
		if sid.startswith("dfyfilm"):  # 最后会有一张非 DICOM 图片。
			continue

		# 只有先读取一个影像才能确定目录的名字。
		first = await _get_dcm(ws, hospital_id, study, sid, 0)
		ds = dcmread(BytesIO(first))

		if not study_dir:
			study_dir = _get_save_dir(ds)
			print(f"下载 szjudianyun 的 DICOM 到：{study_dir}")

		description = ds.SeriesDescription or "定位像"
		dir_ = SeriesDirectory(study_dir, ds.SeriesNumber, description, sizes[sid])
		dir_.get(0, "dcm").write_bytes(first)

		# 这里需要跳过已经下载的一个，tqdm 的迭代式写法好像做不到。
		with tqdm(initial=1, total=sizes[sid], desc=description, unit="张", file=sys.stdout) as progress:
			for i in range(1, sizes[sid]):
				data = await _get_dcm(ws, hospital_id, study, sid, i)
				progress.update(1)
				dir_.get(i, "dcm").write_bytes(data)


async def run(url):
	t = "".join(random.choices(string.ascii_letters + string.digits, k=7))

	url = URL(url)
	hospital_id = url.query["a"]
	study = url.query["b"]
	password = url.query["c"]

	async with new_http_client(base_url) as client:
		async with client.get(f"/socket.io/?EIO=3&transport=polling&t={t}") as response:
			text = await response.text()
			text = text[text.index("{"): text.rindex("}") + 1]
			sid = json.loads(text)["sid"]

		# aiohttp 不要求使用 ws: 协议，默认的 http: 也行。
		async with client.ws_connect(f"/socket.io/?EIO=3&transport=websocket&sid={sid}") as ws:
			await ws.send_str("2probe")
			await anext(ws)
			await ws.send_str("5")

			await _send_message(ws, 42, type="saveC", hospital_id=hospital_id, study=study, password=password)
			message = await anext(ws)
			await download_study(ws, json.loads(message.data[2:])[1])
