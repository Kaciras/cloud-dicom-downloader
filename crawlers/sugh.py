from yarl import URL

from crawlers._utils import new_http_client, SeriesDirectory, tqdme, suggest_save_dir


async def run(share_url: str):
	address = URL(share_url)
	async with new_http_client(address.origin()) as client:
		params = {
			"clinicalShareToken": address.query["clinicalShareToken"],
			"shareCode": "",
			# 还有个 _ts 参数随机 base62 还缺几个字，估计是防缓存的就不加了。
		}
		async with client.get("/api/cloudfilm/api/studyInfo/getClinicalByShareCode", params=params) as response:
			body = await response.json()
			if body["code"] != "200":
				raise Exception(body["message"])
			study_uid, clinical = body["data"]["studyUid"], body["data"]["params"]

		params = {
			"systemCode": "cloudfilm",
			"studyUid": study_uid,
			"orgCode": clinical["orgCode"],
			"purview": "1",
		}
		headers = {
			"Referer": share_url,
			"token": address.query["clinicalShareToken"],
		}
		async with client.get("/api/cloudfilm-mgt/api/v1/study/json/index", params=params, headers=headers) as response:
			body = await response.json()
			if body["code"] != "200":
				raise Exception(body["message"])
			data = body["data"][0]
			info, series_list = data["std"], data["sers"]

		study_dir = suggest_save_dir(clinical["patientName"], info["studyDescription"], info["studyDateTime"])
		print(f"下载篮网云电子胶片到：{study_dir}")

		headers = {
			"orgCode": clinical["orgCode"],
			"systemCode": "cloudfilm",
			"Referer": share_url,
			"token": address.query["clinicalShareToken"],
		}
		for series in series_list.values():
			# 这里的 StudyUID 跟第一个请求返回的的有可能不一样。
			url = "/api/cloudfilm-mgt/api/v1/dicom/studies/" + info["studyUID"]
			url = url + "/series/" + series["seriesUID"]

			desc, number, instances = series["seriesDescription"], series["seriesNumber"], series["imgs"]
			dir_ = SeriesDirectory(study_dir, number, desc, len(instances))

			for i, instance in tqdme(instances.values(), desc=desc):
				async with client.get(f"{url}/instances/{instance['imageUID']}/", headers=headers) as response:
					dir_.get(i, "dcm").write_bytes(await response.read())
