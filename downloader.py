import asyncio
import sys

from yarl import URL

from crawlers import szjudianyun, hinacom, cq12320, shdc, zscloud, ftimage, mtywcloud, yzhcloud, sugh


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
	elif host == "app.ftimage.cn" or host == "yyx.ftimage.cn":
		module_ = ftimage
	elif host == "m.yzhcloud.com":
		module_ = yzhcloud
	elif host == "ss.mtywcloud.com":
		module_ = mtywcloud
	elif host == "work.sugh.net":
		module_ = sugh
	else:
		return print("不支持的网站，详情见 README.md")

	await module_.run(*sys.argv[1:])


if __name__ == "__main__":
	asyncio.run(main())
