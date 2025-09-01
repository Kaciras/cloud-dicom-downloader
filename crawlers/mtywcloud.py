import re
import urllib.parse
import uuid
from pathlib import Path

from Cryptodome.Cipher import AES
from yarl import URL

from crawlers._utils import new_http_client, pkcs7_pad, SeriesDirectory, tqdme

# data = b"71bac47413f0db80c5006615bead82b91dbe2d1b5878843774836a372bc351f126b63d69d304c17e130b1ade75d83470eaed61ebfbfb1b345735ef7cc6040595f6f9776cb46acc0b5f88f73a47717f3035e01a7afc5c7aaf3a9f11d3f634fbfda9e6b0a77fc3d206e0c1d346833640c394adbd3b5ba51314937e6fea03b98e445b91496d435beff36c4d774c51a9eee6a53095bd5187a6d094ac67fa286b0fbc3bf299b61311965fb204275b34072cbcec8d5aa4dcf040328dff522a52a16c93b1c0cfdeed8e5dbf0e975e29fc354c0b934e9a6d2cfeee809a3d29aabdbc12fb01448f228bea204bfdb68d7bfde68ca80c794a10e80498c19ce010d173d7bb39"
# inp = b"DicomDirPath=http%3A%2F%2Fjxyy-20230928%2Foos-cn.ctyunapi.cn%2F12330400470890351D%2F2025%2F08%2F29%2FExam%2F65ad13bd-b005-4347-987f-d21ca13674dd%2FExam%2FExamImage%2F38bf629b-e99c-4738-af96-abe56480600b%2FDICOMDIR&OrganizationID=12330400470890351D"

TIME_SEPS = re.compile(r"[-: ]")

_key = b"561382DAD3AE48A89AC3003E15D75CC0"
_iv = b"1234567890000000"


def encrypt_aes(data: str):
	data = pkcs7_pad(data.encode())
	cipher = AES.new(_key, AES.MODE_CBC, _iv)
	return cipher.encrypt(data).hex()


async def run(url):
	u = URL(url)
	data = urllib.parse.quote(u.query["DicomDirPath"], safe='')
	data = "DicomDirPath=" + data + "&OrganizationID=" + u.query["OrganizationID"]
	datab64 = encrypt_aes(data)

	async with new_http_client("https://ss.mtywcloud.com") as client:
		async with client.get(url) as response:
			client.headers["Referer"] = str(response.url)

		ck = str(uuid.uuid4())
		async with client.post("ICCWebClient/Common/Connect?key=" + ck) as response:
			body = await response.json()
			if body["status"] != "OK":
				raise Exception(body)

		async with client.post("ICCWebClient/api/Study/Info?data=" + datab64) as response:
			body = await response.json()
			if not body["Success"]:
				raise Exception(body)
			info = body["Data"][0]

		patient, exam, date = info["PatientName"], info["ModalitiesInStudy"], info["StudyDateTime"]
		date = TIME_SEPS.sub("", date)
		study_dir = Path(f"download/{patient}-{exam}-{date}")
		for series in info["SeriesList"]:
			desc = series["SeriesDescription"] or "定位像"
			dir_ = SeriesDirectory(study_dir / desc, series["ImageCount"])
			for i, image in tqdme(series["ImageList"], desc=desc):
				params = {
					"sopInstanceUID": image["SOPInstanceUID"],
					"seriesInstanceUID": image["SeriesInstanceUID"],
					"studyInstanceUID": image["StudyInstanceUID"],
					"imagePath": image["ImagePath"],
					"httpPath": "null",
					"retrieveAE": "",
					"OrganizationID": u.query["OrganizationID"],
				}
				async with client.get("/ICCWebClient/api/Dicom/File", params=params) as response:
					dir_.get(i, "dcm").write_bytes(await response.read())
