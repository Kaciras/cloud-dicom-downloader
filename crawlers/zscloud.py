import asyncio
import base64
import json
import logging
import random
from datetime import datetime
from urllib.parse import parse_qsl

from Cryptodome.Cipher import AES
from yarl import URL

from crawlers._utils import new_http_client, SeriesDirectory, tqdme, pkcs7_unpad, suggest_save_dir

# 加载时计算的常量，网站更新可能变（已遇到一次）。
_LAST_KEY = "c57b1589172b85531c2dbad73c5e9056"


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


class TokenManager:
	"""管理访问令牌的获取和刷新"""

	def __init__(self, client):
		self.client = client
		self._token = None
		self._lock = asyncio.Lock()
		self._logger = logging.getLogger(__name__)

	async def get_token(self):
		"""获取有效的访问令牌，如果需要则自动刷新"""
		async with self._lock:
			if self._token is None:
				await self._refresh_token()
			return self._token

	async def _refresh_token(self):
		"""刷新访问令牌"""
		self._logger.info("正在刷新访问令牌...")
		try:
			async with self.client.get("/viewer/2d/Dapeng/Viewer/GetCredentialsToken") as response:
				body = await response.json()
				body = json.loads(body["result"])
				self._token = "Bearer " + body["access_token"]
				self._logger.info("访问令牌刷新成功")
		except Exception as e:
			self._logger.error(f"刷新访问令牌失败: {e}")
			raise

async def _call_image_service_with_refresh(client, token_manager, params, max_retries=3):
	"""调用图像服务，如果令牌过期则自动重试"""
	for attempt in range(max_retries):
		try:
			token = await token_manager.get_token()
			params["randnum"] = random.uniform(0, 1)
			response = await client.get(
				"/vna/image/Home/ImageService",
				params=params,
				headers={"Authorization": token}
			)

			# 读取响应数据进行检查
			response_data = await response.read()

			# 如果响应数据小于1KB，可能是错误响应，检查是否为令牌过期
			if len(response_data) < 1024:
				try:
					response_json = json.loads(response_data.decode())
					# 检查特定的令牌过期错误码
					if response_json.get("msgCode") == "MESSAGE_AUTH_TOKEN_REVOKED":
						if attempt == max_retries - 1:
							raise Exception(f"令牌刷新失败，已达到最大重试次数: {response_json}")
						token_manager._logger.info("检测到令牌已过期 (Uff8109)，正在刷新...")
						await token_manager._refresh_token()
						continue
				except (json.JSONDecodeError, UnicodeDecodeError):
					# 如果不是JSON格式，说明可能是其他类型的响应，直接返回
					pass

			# 创建一个新的响应对象来包装数据
			# 由于我们已经读取了response数据，需要重新构造响应
			class WrappedResponse:
				def __init__(self, original_response, data):
					self._response = original_response
					self._data = data
					self.status = original_response.status
					self.headers = original_response.headers
					self.content_type = original_response.content_type

				async def read(self):
					return self._data

				async def json(self):
					return json.loads(self._data.decode())

				async def text(self):
					return self._data.decode()

				# 支持异步上下文管理器协议
				async def __aenter__(self):
					return self

				async def __aexit__(self, *args):
					# 原始响应已经被读取，无需关闭
					pass

			return WrappedResponse(response, response_data)

		except Exception as e:
			if attempt == max_retries - 1:
				raise
			# 对于其他类型的错误，也尝试刷新令牌后重试
			token_manager._logger.info(f"请求失败，尝试刷新令牌后重试: {e}")
			await token_manager._refresh_token()
			continue



async def run(share_url):
	code = dict(parse_qsl(share_url[share_url.rfind("?") + 1:]))["code"]
	origin = str(URL(share_url).origin())

	async with new_http_client(origin, headers={"Referer": origin}) as client:
		# 设置日志
		logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
		logger = logging.getLogger(__name__)

		async with client.get("/film/api/m/config/getConfigs") as response:
			raw = await response.text()
			config = json.loads(_decrypt_aes_without_iv(raw))
			cetus_aes_key = config["cetusAESKey"]

		async with client.post("/film/api/m/doctor/getStudyByShareCodeWithToken", json={"code": code}) as response:
			body = await response.json()
			if body["code"] != "U000000":
				raise Exception(body["data"])

			data = _cetus_decrypt_aes(cetus_aes_key, body["data"]["encryptionStudyInfo"])
			study = json.loads(data)["records"][0]

			save_to = suggest_save_dir(
				study["patientName"],
				study["procedureItemName"],
				str(datetime.fromtimestamp(study["studyDatetime"] / 1000))
			)
			print(f'保存到: {save_to}')
			info = study["studyLevelList"][0]

		# 初始化令牌管理器
		token_manager = TokenManager(client)

		params = {
			"CommandType": "GetHierachy",
			"StudyUID": info["studyInstanceUid"],
			"UniqueID": info["uniqueId"],
			"LocationCode": info["orgCode"],
			"UserId": "UIH",
			"appendTags": "PI-film-include",
			"includeDeleted": "false",
		}
		async with await _call_image_service_with_refresh(client, token_manager, params) as response:
			body = await response.json()
			series_list = body["PatientInfo"]["StudyList"][0]["SeriesList"]

		for series in series_list:
			desc, number, slices = series["SeriesDes"], series["SeriesNum"], series["ImageList"]
			dir_ = SeriesDirectory(save_to, number, desc, len(slices))

			for i, image in tqdme(slices, desc=desc):
				params = {
					"CommandType": "GetImage",
					"ContentType": "application/dicom",
					"ObjectUID": image["UID"],
					"StudyUID": info["studyInstanceUid"],
					"SeriesUID": series["UID"],
					"includeDeleted": "false",
				}
				async with await _call_image_service_with_refresh(client, token_manager, params) as response:
					dir_.get(i, "dcm").write_bytes(await response.read())
