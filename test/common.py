from pytest import mark

from crawlers._utils import pathify


@mark.parametrize('text, expected', [
	['|*?"', "｜＊？'"],
	[' p/a\\t/h ', 'p／a＼t／h'],
	['Size > 5', 'Size ＞ 5',],
	['Size < 5', 'Size ＜ 5',],
	['Recon 2: 5mm', 'Recon 2： 5mm'],
])
def test_me(text, expected):
	assert pathify(text) == expected
