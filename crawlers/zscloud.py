import base64
import json
import random
from pathlib import Path
from urllib.parse import parse_qsl

from Cryptodome.Cipher import AES
from yarl import URL

from crawlers._utils import new_http_client, SeriesDirectory, pathify, tqdme

# 在 index-5e0ce69c.js 里通过常量计算出来的，应该变得没那么频繁吧。
_LAST_KEY = "c6657583e265f4ca"


def pkcs7_unpad(data: bytes):
	return data[:-data[-1]]


def _decrypt_aes_without_iv(input_: str):
	secret = _LAST_KEY.encode("utf-8")
	input_ = base64.b64decode(input_.encode())

	cipher = AES.new(secret, AES.MODE_ECB)
	decrypted = cipher.decrypt(input_)
	return pkcs7_unpad(decrypted).decode("utf-8")


def _cetus_decrypt_aes(cetus: dict, input_: str):
	key = cetus["cipherSecretKey"].encode("utf-8")
	iv = cetus["cipherIv"].encode("utf-8")
	input_ = base64.b64decode(input_.encode())

	cipher = AES.new(key, AES.MODE_CBC, iv)
	decrypted = cipher.decrypt(input_)
	return pkcs7_unpad(decrypted).decode("utf-8")


def _get_save_dir(study: dict):
	date = study["studyDatetime"] // 1000
	exam = study["procedureItemName"]
	patient = study["patientName"]
	return Path(f"download/{patient}-{exam}-{date}")


def _call_image_service(client, token, params):
	params["randnum"] = random.uniform(0, 1)
	return client.get(
		"/vna/image/Home/ImageService",
		params=params,
		headers={"Authorization": token}
	)


async def run(share_url):
	code = dict(parse_qsl(share_url[share_url.rfind("?") + 1:]))["code"]
	origin = str(URL(share_url).origin())

	async with new_http_client(origin, headers={"Referer": origin}) as client:

		async with client.get("/film/api/m/config/getConfigs") as response:
			raw = await response.text()
			config = json.loads(_decrypt_aes_without_iv(raw))
			cetus_aes_key = config["cetusAESKey"]

		async with client.post("/film/api/m/doctor/getStudyByShareCodeWithToken", json={"code": code}) as response:
			body = await response.json()
			if body["code"] != "U000000":
				raise Exception(body["data"])

			# 响应里说 Token 的有效期是 3600，一个小时应该能下完，就不刷新了。
			access_token = body["data"]["uapToken"]

			data = _cetus_decrypt_aes(cetus_aes_key, body["data"]["encryptionStudyInfo"])
			study = json.loads(data)["records"][0]

			save_to = _get_save_dir(study)
			print(f'保存到: {save_to}')

			info = study["studyLevelList"][0]

		async with client.get("/viewer/2d/Dapeng/Viewer/GetCredentialsToken") as response:
			body = await response.json()
			body = json.loads(body["result"])
			credentials_token = "Bearer " + body["access_token"]

		params = {
			"CommandType": "GetHierachy",
			"StudyUID": info["studyInstanceUid"],
			"UniqueID": info["uniqueId"],
			"LocationCode": info["orgCode"],
			"UserId": "UIH",
			"appendTags": "PI-film-include",
			"includeDeleted": "false",
		}
		async with _call_image_service(client, access_token, params) as response:
			body = await response.json()
			series_list = body["PatientInfo"]["StudyList"][0]["SeriesList"]

		for series in series_list:
			desc = pathify(series["SeriesDes"] or "Unnamed")
			slices = series["ImageList"]
			dir_ = SeriesDirectory(save_to / desc, len(slices))

			for i, image in tqdme(slices, desc=desc):
				params = {
					"CommandType": "GetImage",
					"ContentType": "application/dicom",
					"ObjectUID": image["UID"],
					"StudyUID": info["studyInstanceUid"],
					"SeriesUID": series["UID"],
					"includeDeleted": "false",
				}
				async with _call_image_service(client, credentials_token, params) as response:
					dir_.get(i, "dcm").write_bytes(await response.read())
