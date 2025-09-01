import re
import urllib.parse
from pathlib import Path

from Cryptodome.Cipher import AES
from yarl import URL

from crawlers._utils import new_http_client, pkcs7_pad, SeriesDirectory, tqdme

TIME_SEPS = re.compile(r"[-: ]")

_key = b"561382DAD3AE48A89AC3003E15D75CC0"
_iv = b"1234567890000000"


def encrypt_aes(data: str):
	data = pkcs7_pad(data.encode())
	cipher = AES.new(_key, AES.MODE_CBC, _iv)
	return cipher.encrypt(data).hex()


async def run(url):
	query = URL(url).query
	p, o = urllib.parse.quote_plus(query["DicomDirPath"]), query["OrganizationID"]
	info_query = encrypt_aes(f"DicomDirPath={p}&OrganizationID={o}")

	async with new_http_client("https://ss.mtywcloud.com") as client:
		async with client.get(url) as response:
			client.headers["Referer"] = str(response.url)

		async with client.post("ICCWebClient/api/Study/Info?data=" + info_query) as response:
			body = await response.json()
			if not body["Success"]:
				raise Exception(body["Message"])
			info = body["Data"][0]

		patient, exam, date = info["PatientName"], info["ModalitiesInStudy"], info["StudyDateTime"]
		date = TIME_SEPS.sub("", date)
		study_dir = Path(f"download/{patient}-{exam}-{date}")

		for series in info["SeriesList"]:
			desc = series["SeriesDescription"] or "定位像"
			slices = series["ImageList"]
			dir_ = SeriesDirectory(study_dir / desc, len(slices))
			for i, image in tqdme(slices, desc=desc):
				params = {
					"sopInstanceUID": image["SOPInstanceUID"],
					"seriesInstanceUID": image["SeriesInstanceUID"],
					"studyInstanceUID": image["StudyInstanceUID"],
					"imagePath": image["ImagePath"],
					"httpPath": "null",
					"retrieveAE": "",
					"OrganizationID": query["OrganizationID"],
				}
				async with client.get("/ICCWebClient/api/Dicom/File", params=params) as response:
					dir_.get(i, "dcm").write_bytes(await response.read())
