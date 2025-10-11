from yarl import URL

from crawlers._utils import new_http_client, SeriesDirectory, tqdme, suggest_save_dir


async def run(share_url: str):
	address = URL(share_url)
	study_uid = address.query["study_instance_uid"]

	async with new_http_client(address.origin()) as client:
		client.headers["Referer"] = str(address.origin())
		client.headers["Origin"] = str(address.origin())

		params = {
			"study_instance_uid": study_uid,
			"org_id": address.query["org_id"],
		}
		async with client.get("w_viewer_2/index.php/home/index/ajax_get_patient_study", params=params) as response:
			info = await response.json()

		cdn = URL(info["storage"]).with_scheme("https")
		study_dir = suggest_save_dir(info["patient_name"], info["checkitems"], info["study_date"])
		print(f"下载医众数字影像到：{study_dir}")

		for series in info["series"]:
			instances = series["instance_ids"].split(",")
			number = series["series_number"]
			desc = series["series_description"]
			dir_ = SeriesDirectory(study_dir, number, desc, len(instances))

			for i, name in tqdme(instances, desc=desc):
				# 有可能出现 PNG、JPG 截屏图片作为一个序列。
				sep, ext = name.find("|"), "dcm"
				if sep != -1:
					name, ext = name[:sep], name[sep + 1:]

				u = cdn.joinpath(f"{study_uid}/{series['series_number']}.{name}.{ext}")
				async with client.get(u) as response:
					dir_.get(i, "dcm").write_bytes(await response.read())
