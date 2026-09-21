import re
import sys
import xml.etree.ElementTree as ET

import aiohttp
from yarl import URL

from crawlers._utils import new_http_client, SeriesDirectory, tqdme, suggest_save_dir

_CDATA_RE = re.compile(r'<!\[CDATA\[(.*?)\]\]>', re.DOTALL)
_DATE_RE = re.compile(r'/(\d{8})[\\/]')


async def run(share_url: str, *args):
	address = URL(share_url)
	origin = address.origin()

	conn = aiohttp.TCPConnector(ssl=False)
	async with new_http_client(origin, connector=conn) as client:
		headers = {
			"Referer": share_url,
			"Origin": str(origin),
		}

		# 1. 建立会话以获得 ASP.NET_SessionId
		async with client.get(share_url, headers=headers):
			pass

		# 2. 调用 getWS 获取检查和序列元数据
		params = {
			"username": address.query.get("username", ""),
			"password": address.query.get("password", ""),
			"key": address.query.get("key", ""),
			"value": address.query.get("value", ""),
			"serid": address.query.get("serid", ""),
			"imagetype": address.query.get("imagetype", "11"),
			"pat": address.query.get("pat", "1"),
			"urltoken": address.query["urltoken"],
		}
		async with client.post("Dicom/getWS", data=params, headers=headers) as response:
			body = await response.json(content_type=None)

		if not body or not body.get("result"):
			raise Exception(f"获取检查信息失败: {body.get('Message', '未知错误')}")

		xml_str = body["result"]
		# 解码 HTML 转义字符
		xml_str = (
			xml_str.replace("&lt;", "<")
			.replace("&gt;", ">")
			.replace("&amp;", "&")
			.replace("&apos;", "'")
			.replace("&quot;", '"')
		)
		root = ET.fromstring(xml_str)

		patient = root.find("PATIENTINFO")
		name = patient.findtext("NAME") if patient is not None else "Unknown"
		place = patient.findtext("F_STU_PLACE") if patient is not None else "CT"
		stu_no = patient.findtext("F_STU_NO") if patient is not None else ""

		date = stu_no[:8] if len(stu_no) >= 8 and stu_no[:8].isdigit() else ""
		if not date:
			m = _DATE_RE.search(xml_str)
			if m:
				date = m.group(1)

		study_dir = suggest_save_dir(name.strip(), place.strip(), date.strip())
		print(f"下载济宁市第一人民医院云影像到：{study_dir}")

		series_elements = root.findall("SERIES")
		for seq_idx, series_elem in enumerate(series_elements, start=1):
			sid_raw = series_elem.findtext("SERRIES_ID") or ""
			sname_raw = series_elem.findtext("SERIES_NAME") or ""
			sid = _CDATA_RE.sub(r"\1", sid_raw).strip()
			sname = _CDATA_RE.sub(r"\1", sname_raw).strip()
			desc = sname or sid or f"Series_{seq_idx}"

			instances = [i.text for i in series_elem.findall("I") if i.text]
			if not instances:
				continue

			dir_ = SeriesDirectory(study_dir, seq_idx, desc, len(instances))
			for i, img_url in tqdme(instances, desc=desc):
				# 触发服务端转储生成缓存
				async with client.post("Dicom/DownImage", data={"url": img_url}, headers=headers) as resp:
					down_res = await resp.json(content_type=None)

				if not down_res.get("state") or not down_res.get("result"):
					print(f"\n切片 {img_url} 获取失败: {down_res.get('message', '未知错误')}", file=sys.stderr)
					continue

				cache_rel = down_res["result"].lstrip("/")
				cache_url = f"CacheImage/{cache_rel}"
				async with client.get(cache_url, headers=headers) as resp:
					dir_.get(i, "dcm").write_bytes(await resp.read())
