import json
import re
from urllib.parse import parse_qsl

from crawlers._utils import new_http_client
from crawlers.hinacom import HinacomDownloader

_TARGET_URL = re.compile(r'var TARGET_URL = "([^"]+)"')
_BASE = "https://mdmis.cq12320.cn/wcs1/mdmis-app/h5"


async def run(share_url, *args):
	query = dict(parse_qsl(share_url[share_url.rfind("?") + 1:]))
	client = new_http_client()
	print(f"下载海纳医信 DICOM（重庆卫建委），share_id: {query["share_id"]}")

	# 先是入口页面，它会重定向到登录页并设置一个 SF_cookie_15
	(await client.get(share_url)).close()

	# 拿 hospital_code 和 study_primary_id
	form = {
		"content": query["content"],
		"share_id": query["share_id"]
	}
	async with client.post(f"{_BASE}/api/share/check/time", json=form) as response:
		body = await response.json()
		extend = json.loads(body["data"]["extend"])
		study_id, hospital_code = extend["study_primary_id"], extend["hospital_code"]

	print(f"hospital_code: {hospital_code}")
	print(f"study_primary_id: {study_id}\n")

	# 拿 ZFP_SessionId, ZFPXAUTH，注意这里自动重定向了一次。
	async with client.get(f"{_BASE}/api/qinming_h5/api/ch/report/PacsEntry.aspx?hospitalCode={hospital_code}&studyPrimaryId={study_id}") as response:
		matches = _TARGET_URL.search(await response.text())
		viewer_url = str(response.real_url.origin()) + matches.group(1)

	async with await HinacomDownloader.from_url(client, viewer_url) as downloader:
		await downloader.download_all("--raw" in args)
