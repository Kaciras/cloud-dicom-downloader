import hashlib
import random
import re
import string
import sys
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

from tqdm import tqdm
from yarl import URL

from crawlers._utils import new_http_client, pathify

TABLE_62 = string.digits + string.ascii_lowercase + string.ascii_uppercase

# 页面代码里找到一个 AES 加密算出来的，是个固定值。
# 但也可能随着网站更新变化，如果改变频繁可能需要换成跑浏览器爬虫的方案。
KEY = "5fbcVzmBJNUsw53#"

# 根据逆向找到的，随机 6 位 Base62。
NONCE = "".join(random.choices(TABLE_62, k=6))

TIME_SEPS = re.compile(r"[-: ]")


def _sign_parameters(query: dict, params: dict):
	"""
	该网站的 API 请求有签名机制，算法倒不复杂，扒下代码就能还原。
	"""
	params["nonce_str"] = NONCE
	params["token"] = query["token"]
	input_ = urlencode(params) + "&key=" + KEY
	params["sign"] = hashlib.md5(input_.encode()).hexdigest()


def _get_auth(query: dict, image_name: str):
	"""
	DCM 文件的请求又有认证，用得是请求头，同样扒代码可以分析出来。
	"""
	parts = query["sid"], query["token"], str(round(time.time() * 1000))
	token = hashlib.md5(";".join(parts + (image_name, KEY)).encode()).hexdigest()
	return "Basic " + ";".join(parts + (token,))


def _get_save_dir(study: dict):
	date = TIME_SEPS.sub("", study["study_datetime"])
	exam = pathify(study["description"])
	patient = pathify(study["patient"]["name"])
	return Path(f"download/{patient}-{exam}-{date}")


# 这个网站没有烦人的跳转登录，但是有简单的 API 签名。
async def run(share_url: str):
	query = dict(parse_qsl(share_url[share_url.rfind("?") + 1:]))
	origin = URL(share_url).origin()

	print(f"下载申康 DICOM，报告 ID：{query["sid"]}")

	async with new_http_client(base_url=origin) as client:
		# 先拿检查基本信息，用于生成保存的目录名。
		p0 = {"sid": query["sid"], "mode": 0}
		_sign_parameters(query, p0)
		async with client.get("/api001/study/detail", params=p0) as response:
			detail = await response.json(content_type=None)
			if detail["code"] != 0:
				raise Exception(f"错误（{detail['code']}），链接过期，或是网站更新了")

		p1 = { "sid": query["sid"] }
		_sign_parameters(query, p1)
		async with client.get("/api001/series/list", params=p1) as response:
			data = await response.json(content_type=None)
			series_list = data["result"]

		save_to = _get_save_dir(detail["study"])
		print(f'保存到: {save_to}\n')

		for series in series_list:
			desc = pathify(series["description"]) or "Unnamed"
			dir_ = save_to / desc
			dir_.mkdir(parents=True, exist_ok=True)

			tasks = tqdm(series["names"].split(","), desc=desc, unit="张", file=sys.stdout)
			for i, name in enumerate(tasks, 1):
				path = "/rawdata/indata/" + series["source_folder"] + "/" + name
				headers = {
					"Authorization": _get_auth(query, name),
					"Referer": "https://ylyyx.shdc.org.cn/",
				}

				async with client.get(path, headers=headers) as response:
					file = await response.read()
					dir_.joinpath(f"{i}.dcm").write_bytes(file)
