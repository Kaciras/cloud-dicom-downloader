from pathlib import Path

import pytest
from aiohttp import web, ClientResponseError
from pytest import mark

# noinspection PyProtectedMember
from crawlers._utils import pathify, new_http_client, make_unique_dir


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


def test_make_unique_dir():
	path = Path("download/__test_dir")
	created = make_unique_dir(path)

	assert created.is_dir()
	assert created == path
	created.rmdir()


def test_make_unique_dir_2():
	path = Path("download/__test_dir (1)")
	path.mkdir(parents=True)
	created = make_unique_dir(path)

	assert created.is_dir()
	assert created == Path("download/__test_dir (2)")
	path.rmdir()
	created.rmdir()
