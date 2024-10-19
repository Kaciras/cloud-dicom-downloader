import asyncio
import sys

from yarl import URL

from crawlers import szjudianyun, hinacom


def main():
	host = URL(sys.argv[1]).host

	if host.endswith(".medicalimagecloud.com"):
		module_ = hinacom
	elif host == "qr.szjudianyun.com":
		module_ = szjudianyun
	else:
		return print("不支持的网站，详情见 README.md")

	return module_.run(*sys.argv[1:])


if __name__ == "__main__":
	asyncio.run(main())
