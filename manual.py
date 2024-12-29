import asyncio
import io
from pathlib import Path

from aiohttp.web_response import Response as AioResponse
from playwright.async_api import async_playwright, Playwright, Response

index = 0


async def dump(directory: Path, response: Response):
	global index
	index += 1
	with directory.joinpath(F"{index}.xhr").open("wb") as fp:
		fp.write(f"HTTP1/1 {response.status} {response.status_text}".encode())
		for k, v in response.headers.items():
			fp.write(f"\r\n{k}:{v}".encode())
		fp.write(b"\r\n\r\n")
		fp.write(await response.body())


def deserialize(xhr: Path):
	with xhr.open("rb") as fp:
		reader = io.TextIOWrapper(fp, encoding="utf-8", newline="\r\n")
		_, s, reason = reader.readline().rstrip("\r\n").split(" ", 2)
		headers: list[(str, str)] = []
		while True:
			header = reader.readline().rstrip("\r\n")
			if not header:
				break
			kv = header.split(":", 1)
			headers.append(tuple(kv))
		body = fp.read()
	return AioResponse(body=body, status=int(s), reason=reason, headers=headers)


async def run(playwright: Playwright):
	chromium = playwright.chromium  # or "firefox" or "webkit".
	browser = await chromium.launch(
		executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
		headless=False,
	)
	page = await browser.new_page()
	page.context.on("response", intercept)
	await page.goto("https://tieba.baidu.com/index.html")
	# other actions...
	await browser.close()


async def intercept(response: Response):
	await dump(Path("exports"), response)


async def main():
	async with async_playwright() as playwright:
		await run(playwright)


asyncio.run(main())

gg = deserialize(Path("exports/1.xhr"))
print(gg)
