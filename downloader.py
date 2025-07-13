import asyncio
import sys

from yarl import URL

from crawlers import szjudianyun, hinacom, cq12320, shdc, zscloud, ftimage


async def main():
	host = URL(sys.argv[1]).host

	if host.endswith(".medicalimagecloud.com"):
		module_ = hinacom
	elif host == "mdmis.cq12320.cn":
		module_ = cq12320
	elif host == "qr.szjudianyun.com":
		module_ = szjudianyun
	elif host == "ylyyx.shdc.org.cn":
		module_ = shdc
	elif host == "zscloud.zs-hospital.sh.cn":
		module_ = zscloud
	elif host == "app.ftimage.cn":
		module_ = ftimage
	else:
		return print("不支持的网站，详情见 README.md")

	await module_.run(*sys.argv[1:])


if __name__ == "__main__":
	asyncio.run(main())
