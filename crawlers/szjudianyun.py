"""
下载 szjudianyun.com 上面的云影像，爬虫流程见：
https://blog.kaciras.com/article/39/download-raw-dicom-from-cloud-ct-viewer
"""
import json
import random
import string
import sys
from pathlib import Path

import aiohttp
from tqdm import tqdm
from yarl import URL

# 常量，是一堆 DICOM 的 TAG ID，由 b1u2d3d4h5a 分隔。
tag = "0x00100010b1u2d3d4h5a0x00101001b1u2d3d4h5a0x00100020b1u2d3d4h5a0x00100030b1u2d3d4h5a0x00100040b1u2d3d4h5a0x00101010b1u2d3d4h5a0x00080020b1u2d3d4h5a0x00080030b1u2d3d4h5a0x00180015b1u2d3d4h5a0x00180050b1u2d3d4h5a0x00180088b1u2d3d4h5a0x00080080b1u2d3d4h5a0x00181100b1u2d3d4h5a0x00280030b1u2d3d4h5a0x00080060b1u2d3d4h5a0x00200032b1u2d3d4h5a0x00200037b1u2d3d4h5a0x00280030b1u2d3d4h5a0x00280010b1u2d3d4h5a0x00280011b1u2d3d4h5a0x00080008b1u2d3d4h5a0x00200013b1u2d3d4h5a0x0008103Eb1u2d3d4h5a0x00181030b1u2d3d4h5a0x00080070b1u2d3d4h5a0x00200062b1u2d3d4h5a0x00185101";

# 这网站看上去是个小作坊外包，应该不会有更多域名了。
base = "http://qinniaofu.coolingesaving.com:63001"


def _send_message(ws, id_, **message):
	return ws.send_str(str(id_) + json.dumps(["sendMessage", message]))


async def _request_dcm(ws, hospital_id, study, series, instance):
	await _send_message(
		ws, 42,
		hospital_id=hospital_id,
		study=study,
		tag=tag,
		type="hangC",
		ww="",
		wl="",
		series=series,
		series_in=str(instance))

	# 451 开头的回复消息，没什么用。
	await anext(ws)

	# 第一位 4 是 socket.io 添加的需要跳过。
	return (await anext(ws)).data[1:]


async def run(url):
	t = random.choices(string.ascii_letters + string.digits, k=7)

	url = URL(url)
	hospital_id = url.query["a"]
	study = url.query["b"]
	password = url.query["c"]

	out_dir = Path(f"download/{hospital_id}-{study}")

	async with aiohttp.ClientSession(base, raise_for_status=True) as client:
		#  什么傻逼 qinniao，不会是北大青鸟吧？
		async with client.get(f"/socket.io/?EIO=3&transport=polling&t={t}") as response:
			text = await response.text()
			text = text[text.index("{"): text.rindex("}") + 1]
			sid = json.loads(text)["sid"]

		async with client.ws_connect(f"/socket.io/?EIO=3&transport=websocket&sid={sid}") as ws:
			await ws.send_str("2probe")
			await anext(ws)
			await ws.send_str("5")
			await _send_message(ws, 42, type="saveC", hospital_id=hospital_id, study=study, password=password)
			message = await anext(ws)
			info = json.loads(message.data[2:])[1]
			series_list, sizes = info["series"], info["series_dicom_number"]

			print(f"保存到 {out_dir}，共 {len(series_list)} 张序列")
			for sid in series_list:
				if sid.startswith("dfyfilm"):  # 最后会有一张非 DICOM 图片，跳过。
					continue
				out_dir.joinpath(sid).mkdir(parents=True, exist_ok=True)

				for i in tqdm(range(1, sizes[sid] + 1), desc=sid, unit="张", file=sys.stdout):
					dcm = await _request_dcm(ws, hospital_id, study, sid, i)
					out_dir.joinpath(sid, f"{i}.dcm").write_bytes(dcm)
