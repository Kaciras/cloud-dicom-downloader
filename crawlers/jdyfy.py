import re

from yarl import URL

from crawlers._utils import new_http_client
from crawlers.hinacom import HinacomDownloader

# 元素属性很简单，就直接正则了，懒得再下个解析库。
_hidden_input_re = re.compile(r'<input type="hidden" id="StudyId" name="StudyId" value="([^"]+)" />')


async def run(share_url, *args):
	address = URL(share_url)

	async with new_http_client() as client:
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

		async with await HinacomDownloader.from_viewer_link(client, share_url) as downloader:
			await downloader.download_all("--raw" in args)
