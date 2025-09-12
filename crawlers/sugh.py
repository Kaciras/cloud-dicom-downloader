import random
import string

from yarl import URL

from crawlers._utils import new_http_client, pathify, SeriesDirectory, tqdme, suggest_save_dir


async def run(share_url: str):
	address = URL(share_url)
	async with new_http_client(address.origin()) as client:
		params = {
			"clinicalShareToken": address.query["clinicalShareToken"],
			"shareCode": "",
			"_ts": "".join(random.choices(string.ascii_letters + string.digits, k=8))
		}
		async with client.get("/api/cloudfilm/api/studyInfo/getClinicalByShareCode", params=params) as response:
			body = await response.json()
			if body["code"] != "200":
				raise Exception(body["message"])
			study_uid, up = body["data"]["studyUid"], body["data"]["params"]

		params = {
			"systemCode": "cloudfilm",
			"studyUid": study_uid,
			"orgCode": up["orgCode"],
			"purview": "1",
			"_ts": "".join(random.choices(string.ascii_letters + string.digits, k=8))
		}
		hdrs = {
			"Referer": share_url,
			"token": address.query["clinicalShareToken"],
		}
		async with client.get("/api/cloudfilm-mgt/api/v1/study/json/index", params=params, headers=hdrs) as response:
			body = await response.json()
			if body["code"] != "200":
				raise Exception(body["message"])
			data = body["data"][0]
			info, series_list = data["std"], data["sers"]

		study_dir = suggest_save_dir(up["patientName"], info["studyDescription"], info["studyDateTime"])
		print(f"下载篮网云电子胶片到：{study_dir}")

		hdrs = {
			"orgCode": up["orgCode"],
			"systemCode": "cloudfilm",
			"Referer": share_url,
			"token": address.query["clinicalShareToken"],
		}

		for series in series_list.values():
			url = "/api/cloudfilm-mgt/api/v1/dicom"
			url = url + "/studies/" + study_uid
			url = url + "/series/" + series["seriesUID"]

			desc, instances = series["seriesDescription"], series["imgs"]
			dir_ = SeriesDirectory(study_dir / pathify(desc), len(instances))

			for i, instance in tqdme(instances.values(), desc=desc):
				async with client.get(f"{url}/instances/{instance['imageUID']}/", headers=hdrs) as response:
					dir_.get(i, "dcm").write_bytes(await response.read())

