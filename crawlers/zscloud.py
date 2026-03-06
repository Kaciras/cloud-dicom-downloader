import base64
import hashlib
import json
import math
import random
import urllib.parse
from datetime import datetime
from urllib.parse import parse_qsl

from Cryptodome.Cipher import AES
from yarl import URL

from crawlers._utils import new_http_client, SeriesDirectory, tqdme, pkcs7_unpad, suggest_save_dir

# 加载时计算的常量，网站更新可能变（已遇到一次）。
_LAST_KEY = "c57b1589172b85531c2dbad73c5e9056"

# getTWoParams() 中的硬编码数组，用于解密 encryptionStudyInfo（网站更新可能变）。
_CETUS_KEY = ''.join(chr(v) for v in [54,56,98,57,100,98,100,57,49,102,53,99,51,57,54,48,57,57,100,51,49,101,100,57,51,98,56,53,48,55,97,99])
_CETUS_IV  = ''.join(chr(v) for v in [100,51,57,100,102,99,51,48,100,53,52,56,98,56,52,49])

# makeParams() 中的硬编码盐值，用于 API 请求签名（网站更新可能变）。
_MAKE_PARAMS = "23599a8ad8db0d1e51310376b92843f56d25a41193c3a7870e32df3446ad4700"


def _decrypt_aes_without_iv(input_: str):
	key = base64.b64decode(_LAST_KEY)
	data = base64.b64decode(input_.strip())
	iv  = data[:12]
	tag = data[-16:]
	ct  = data[12:-16]

	cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
	decrypted = cipher.decrypt_and_verify(ct, tag)
	return decrypted.decode("utf-8")


def _cetus_decrypt_aes(input_: str):
	key = _CETUS_KEY.encode("utf-8")
	iv  = _CETUS_IV.encode("utf-8")
	input_ = base64.b64decode(input_.encode())

	cipher = AES.new(key, AES.MODE_CBC, iv)
	decrypted = cipher.decrypt(input_)
	return pkcs7_unpad(decrypted).decode("utf-8")


def _sign_request(auth_token: str, params: dict) -> dict:
	"""Compute X-Request/X-List/X-Source headers as the browser JS addHeader() does."""
	x_request = math.floor(random.random() * 1e8)
	params_str = {k: str(v) if isinstance(v, (int, float)) else v for k, v in params.items()}
	x_list = ','.join(params_str.keys())
	body = json.dumps(params_str, separators=(',', ':'))
	encoded = urllib.parse.quote(body, safe='')
	digest = hashlib.sha256(
		(auth_token + _MAKE_PARAMS + encoded + str(x_request)).encode('utf-8')
	).hexdigest()
	return {'X-Request': str(x_request), 'X-List': x_list, 'X-Source': digest}


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

	async with new_http_client(origin, headers={"Referer": origin + "/film/"}) as client:

		async with client.post("/film/api/m/doctor/getStudyByShareCodeWithToken",
				json={"code": code},
				headers={"Origin": origin}) as response:
			body = await response.json()
			if body["code"] != "U000000":
				raise Exception(body["data"])

			film_token = _decrypt_aes_without_iv(body["data"]["token"])
			data = _cetus_decrypt_aes(body["data"]["encryptionStudyInfo"])
			study = json.loads(data)["records"][0]

			save_to = suggest_save_dir(
				study["patientName"],
				study["procedureItemName"],
				str(datetime.fromtimestamp(study["studyDatetime"] / 1000))
			)
			print(f'保存到: {save_to}')

		hier_params = {
			"imageType": study["procedureOfficeCode"],
			"locationCode": study["orgCode"],
			"accessionNo": study["accessionNo"],
			"source": "CloudFilm",
		}
		sig = _sign_request(film_token, hier_params)
		async with client.get(
			"/film/api/m/report/getHierachy",
			params=hier_params,
			headers={"Authorization": film_token, "Origin": origin, **sig},
		) as response:
			body = await response.json()
			if body["code"] != "U000000":
				raise Exception(body)
			hier = json.loads(body["data"]) if isinstance(body["data"], str) else body["data"]
			study_node = hier["PatientInfo"]["StudyList"][0]
			study_uid = study_node["UID"]
			series_list = study_node["SeriesList"]

		async with client.get("/viewer/2d/Dapeng/Viewer/GetCredentialsToken") as response:
			body = await response.json()
			body = json.loads(body["result"])
			credentials_token = "Bearer " + body["access_token"]

		for series in series_list:
			desc, number, slices = series["SeriesDes"], series["SeriesNum"], series["ImageList"]
			dir_ = SeriesDirectory(save_to, number, desc, len(slices))

			for i, image in tqdme(slices, desc=desc):
				params = {
					"CommandType": "GetImage",
					"ContentType": "application/dicom",
					"ObjectUID": image["UID"],
					"StudyUID": study_uid,
					"SeriesUID": series["UID"],
					"includeDeleted": "false",
				}
				async with _call_image_service(client, credentials_token, params) as response:
					dir_.get(i, "dcm").write_bytes(await response.read())

