import asyncio
import base64
import json
import random
import sys
from pathlib import Path
from urllib.parse import parse_qsl

from Cryptodome.Cipher import AES
from tqdm import tqdm

from crawlers._utils import new_http_client, SeriesDirectory, pathify

_LAST_KEY = "c6657583e265f4ca"


def decrypt_aes_without_iv(input_: str):
	secret = _LAST_KEY.encode("utf-8")
	input_ = base64.b64decode(input_.encode())
	cipher = AES.new(secret, AES.MODE_ECB)
	decrypted = cipher.decrypt(input_)
	return pkcs7_unpad(decrypted).decode("utf-8")


def cetus_decrypt_aes(cetus: dict, input_: str):
	key, iv = cetus["cipherSecretKey"].encode("utf-8"), cetus["cipherIv"].encode("utf-8")
	input_ = base64.b64decode(input_.encode())

	cipher = AES.new(key, AES.MODE_CBC, iv)
	decrypted = cipher.decrypt(input_)
	return pkcs7_unpad(decrypted).decode("utf-8")


def pkcs7_unpad(data: bytes):
	return data[:-data[-1]]


async def run(share_url):
	query = dict(parse_qsl(share_url[share_url.rfind("?") + 1:]))

	async with new_http_client(headers={"Referer": "https://zscloud.zs-hospital.sh.cn/film/"}) as client:

		async with client.get(share_url) as response:
			pass
		async with client.get("https://zscloud.zs-hospital.sh.cn/uap-operation-api/v1/config/get?appKey=film",
		                      raise_for_status=False) as response:
			pass

		async with client.get("https://zscloud.zs-hospital.sh.cn/film/api/m/config/getConfigs") as response:
			raw = await response.text()
			config = json.loads(decrypt_aes_without_iv(raw))
			cetus_aes_key = config["cetusAESKey"]

		async with client.post(
				"https://zscloud.zs-hospital.sh.cn/film/api/m/doctor/getStudyByShareCodeWithToken",
				json={"code": query["code"]}
		) as response:
			body = await response.json()
			if body["code"] != "U000000":
				return print(body)

			# 响应里说 Token 的有效期是 3600，一个小时应该能下完就不刷新了。
			token = body["data"]["token"]
			access_token = body["data"]["uapToken"]

			xxx = cetus_decrypt_aes(cetus_aes_key, body["data"]["encryptionStudyInfo"])
			xxx = json.loads(xxx)
			study = xxx["records"][0]

			dt = study["studyDatetime"] // 1000
			patient = study["patientName"]
			exam = study["procedureItemName"]
			save_to = Path(f"download/{patient}-{exam}-{dt}")
			print(f'保存到: {save_to}')

			info = study["studyLevelList"][0]

		async with client.get(
				"https://zscloud.zs-hospital.sh.cn/viewer/2d/Dapeng/Viewer/GetCredentialsToken") as response:
			body = await response.json()
			body = json.loads(body["result"])
			credentials_token = body["access_token"]

		params0 = {
			"CommandType": "GetHierachy",
			"StudyUID": info["studyInstanceUid"],
			"UniqueID": info["uniqueId"],
			"LocationCode": info["orgCode"],
			"UserId": "UIH",
			"appendTags": "PI-film-include",
			"includeDeleted": "false",
			"randnum": str(random.uniform(0, 1)),
		}
		async with client.get(
				"https://zscloud.zs-hospital.sh.cn/vna/image/Home/ImageService",
				params=params0,
				headers={
					"Authorization": access_token
				}
		) as response:
			body = await response.json()
			series_list = body["PatientInfo"]["StudyList"][0]["SeriesList"]

		for series in series_list:
			desc = pathify(series["SeriesDes"] or "Unnamed")
			slices = series["ImageList"]
			dir_ = SeriesDirectory(save_to / desc, len(slices))

			for i, image in enumerate(tqdm(slices, desc=desc, unit="张", file=sys.stdout)):
				params = {
					"CommandType": "GetImage",
					"ContentType": "application/dicom",
					"ObjectUID": image["UID"],
					"StudyUID": info["studyInstanceUid"],
					"SeriesUID": series["UID"],
					"includeDeleted": "false",
					"randnum": str(random.uniform(0, 1))
				}
				async with client.get(
						"https://zscloud.zs-hospital.sh.cn/vna/image/Home/ImageService",
						params=params,
						headers={
							"Authorization": "Bearer " + credentials_token
						}
				) as response:
					dir_.get(i, "dcm").write_bytes(await response.read())


if __name__ == '__main__':
	asyncio.run(run())
