"""
https://blog.kaciras.com/article/45/download-dicom-files-from-hinacom-cloud-viewer
"""
import random
import re
import string
import sys
import time
from hashlib import md5
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

from tqdm import tqdm
from yarl import URL

from crawlers._utils import new_http_client, pathify, SeriesDirectory

TABLE_62 = string.digits + string.ascii_lowercase + string.ascii_uppercase

# 页面代码里找到一个 AES 加密算出来的，是个固定值。
# 但也可能随着网站更新变化，如果改变频繁可能需要换成跑浏览器爬虫的方案。
KEY = "5fbcVzmBJNUsw53#"

# 根据逆向找到的，随机 6 位 Base62。
NONCE = "".join(random.choices(TABLE_62, k=6))

TIME_SEPS = re.compile(r"[-: ]")


def _sign(query: dict, params: dict):
	"""
	该网站的 API 请求有签名机制，算法倒不复杂，扒下代码就能还原。

	:param query URL 中的参数
	:param params API 请求的参数，签名会添加到上面
	"""
	params["nonce_str"] = NONCE
	if "token" in query:
		params["token"] = query["token"]
	input_ = urlencode(params) + "&key=" + KEY
	params["sign"] = md5(input_.encode()).hexdigest()


def _get_auth(query: dict, image_name: str):
	"""
	DCM 文件的请求又有认证，用得是请求头，同样扒代码可以分析出来。

	:param query URL 中的参数
	:param image_name 图片名，是 8 位大写 HEX
	"""
	parts = query["sid"], query["token"], str(round(time.time() * 1000))
	token = md5(";".join(parts + (image_name, KEY)).encode()).hexdigest()
	return "Basic " + ";".join(parts + (token,))


def _get_save_dir(study: dict):
	# 它这里有好多时间，除此之外还有 update_time、create_time，有些可能为 null。
	date = study.get("study_datetime")
	if not date:
		date = study["study_date"] + study["study_time"]
	date = TIME_SEPS.sub("", date)

	exam = pathify(study["description"] or study["modality_type"])
	patient = pathify(study["patient"]["name"])
	return Path(f"download/{patient}-{exam}-{date}")


async def request(client, query: dict, path: str, form = None, **params):
	_sign(query, params)

	if not form:
		coroutine = client.get(path, params=params)
	else:
		h = {"content-type": "application/x-www-form-urlencoded"}
		coroutine = client.post(path, params=params, headers=h, data=form)

	async with coroutine as response:
		body = await response.json(content_type=None)

	if body["code"] == 0:
		return body

	message = body['msg'] or "从未遇见过的问题，请联系开发者处理"
	raise Exception(f"API 错误（{body['code']}），{message}。")


async def share_verify(client, query: dict):
	form = f"appid={query['appid']}&share_id={query['share_id']}"
	share = await request(client, query, "/api001/share_verify", form)
	share_url = share["url_link"]
	return dict(parse_qsl(share_url[share_url.rfind("?") + 1:]))


# 这个网站没有烦人的跳转登录，但是有简单的 API 签名。
async def run(share_url: str):
	query = dict(parse_qsl(share_url[share_url.rfind("?") + 1:]))
	origin = URL(share_url).origin()

	async with new_http_client(origin) as client:
		# 另一种入口，好像是报告主页面而不是分享的链接。需要先创建一个分享。
		if "share_id" in query:
			query = await share_verify(client, query)

		sid = query["sid"]
		print(f"下载申康医院发展中心的 DICOM，报告 ID：{sid}")

		detail = await request(client, query, "/api001/study/detail", sid=sid, mode=0)
		series_list = await request(client, query, "/api001/series/list", sid=sid)

		save_to = _get_save_dir(detail["study"])
		print(f'保存到: {save_to}\n')

		for series in series_list["result"]:
			desc = pathify(series["description"]) or "Unnamed"
			names = series["names"].split(",")
			dir_ = SeriesDirectory(save_to / desc, len(names))

			tasks = tqdm(names, desc=desc, unit="张", file=sys.stdout)
			for i, name in enumerate(tasks):
				path = "/rawdata/indata/" + series["source_folder"] + "/" + name
				headers = {
					"Authorization": _get_auth(query, name),
					"Referer": "https://ylyyx.shdc.org.cn/",
				}

				async with client.get(path, headers=headers) as response:
					file = await response.read()
					dir_.get(i, "dcm").write_bytes(file)
