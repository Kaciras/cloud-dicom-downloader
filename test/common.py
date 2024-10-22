from pathlib import Path

import pytest
from aiohttp import web, ClientResponseError
from pytest import mark

from crawlers._utils import pathify, new_http_client


@mark.parametrize('text, expected', [
	['|*?"', "｜＊？'"],
	[' p/a\\t/h ', 'p／a＼t／h'],
	['Size > 5', 'Size ＞ 5', ],
	['Size < 5', 'Size ＜ 5', ],
	['Recon 2: 5mm', 'Recon 2： 5mm'],
])
def test_pathify(text, expected):
	assert pathify(text) == expected


async def hello(_):
	return web.Response(status=500, text='Hello, world')


async def test_response_dumping():
	app = web.Application()
	app.router.add_get('/', hello)
	runner = web.AppRunner(app)
	await runner.setup()
	site = web.TCPSite(runner, '[::1]', 12345)
	await site.start()

	client = new_http_client()
	try:
		await client.get('http://[::1]:12345')
		pytest.fail()
	except ClientResponseError:
		assert Path("dump.zip").exists()
	finally:
		await runner.cleanup()
		Path("dump.zip").unlink()
