import re
import sys

from playwright.async_api import Response, BrowserContext
from tqdm import tqdm
from yarl import URL

from crawlers._browser import PlaywrightCrawler, run_with_browser
from crawlers._utils import new_http_client, pathify, SeriesDirectory, suggest_save_dir
from crawlers.hinacom import _write_dicom

# 元素属性很简单，就直接正则了，懒得再下个解析库。
_hidden_input_re = re.compile(r'<input type="hidden" id="StudyId" name="StudyId" value="([^"]+)" />')
_VAR_RE = re.compile(r'var LOAD_IMAGE_CACHE_KEY = "([^"]*)"')


class HinacomCrawlerPW(PlaywrightCrawler):

	def __init__(self, view_link: str):
		self.view_link = view_link

	async def _on_response(self, response: Response):
		asset_name = URL(response.request.url).path

		if asset_name != "/ImageViewer/GetImageSet":
			return

		self.dataset = await response.json()
		print(self.dataset)

		html = await response.frame.content()
		self.cache_key = ck = _VAR_RE.search(html).group(1)
		print(ck)
		is_raw=False

		ds = self.dataset
		save_to = suggest_save_dir(ds["patientName"], ds["studyDescription"], ds["studyDate"])

		for series in self.dataset["displaySets"]:
			name, no, images = pathify(series["description"]) or "Unnamed", series["seriesNumber"], series["images"]
			dir_ = SeriesDirectory(save_to / name, len(images))

			tasks = tqdm(images, desc=name, unit="张", file=sys.stdout)
			for i, info in enumerate(tasks):
				# 图片响应头包含的标签不够，必须每个都请求 GetImageDicomTags。
				tags = await self.get_tags(info)

				# 没有标签的视为非 DCM 文件，跳过。
				if len(tags) == 0:
					continue

				pixels, _ = await self.get_image(info, is_raw)
				_write_dicom(tags, pixels, dir_.get(i, "dcm"))

		self.cks = await response.frame.page.context.cookies()
		await response.frame.page.context.close()

	async def get_tags(self, info):
		api = "http://cloudpacs.jdyfy.com:8001/ImageViewer/GetImageDicomTags"
		params = {
			"studyId": info['studyId'],
			"imageId": info['imageId'],
			"frame": "0",
			"storageNodes": self.dataset["storageNode"] or "",
		}
		response = await self._context.request.get(api, params=params)
		return await response.json()

	async def get_image(self, info, raw: bool):
		s, i = info['studyId'], info['imageId']
		if raw:
			api = f"http://cloudpacs.jdyfy.com:8001/imageservice/api/image/dicom/{s}/{i}/0/0"
		else:
			api = f"http://cloudpacs.jdyfy.com:8001/imageservice/api/image/j2k/{s}/{i}/0/3"

		params = {"ck": self.cache_key}
		if self.dataset["storageNode"]:
			params["storageNodes"] = self.dataset["storageNode"]

		response = await self._context.request.get(api, params=params)
		return await response.body(), response.headers["x-imageframe"]

	async def _do_run(self, context: BrowserContext):
		page = await context.new_page()
		await page.goto(self.view_link, wait_until="commit")
		await context.wait_for_event("close", timeout=0)


async def run(share_url, password=None):
	address, client = URL(share_url), new_http_client()
#http://cloudpacs.jdyfy.com:38081/Study/ViewImage?studyId=b4ab0bac-afef-46cf-aa23-277aaf7c54df
	# 手机尾号验证入口，但实际上 StudyId 写在页面里了，并不需要手机号。
	if address.query["idType"] == "accessionnumber":
		async with client.get(share_url) as response:
			html = await response.text()
			fields = _hidden_input_re.search(html)
			sid = fields.group(1)
			share_url = f"{address.origin()}/Study/ViewImage?studyId={sid}"

	# 影像查看页的 URL 作为入口，从 returnUrl 回到跳转页来进入。
	elif address.query["returnUrl"]:
		share_url = address.query["returnUrl"]

	await run_with_browser(HinacomCrawlerPW(share_url))

	# async with await HinacomDownloader.from_vu(client, share_url) as downloader:
	# 	await downloader.download_all("--raw" in [])
