from pathlib import Path

from yarl import URL

from crawlers._utils import new_http_client, SeriesDirectory, tqdme, pathify


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

		patient, exam, date = info["patient_name"], pathify(info["checkitems"]), info["study_date"]
		cdn = URL(info["storage"]).with_scheme("https")
		study_dir = Path(f"download/{patient}-{exam}-{date}")

		for series in info["series"]:
			instances = series["instance_ids"].split(",")
			desc = series["series_description"]
			dir_ = SeriesDirectory(study_dir / pathify(desc), len(instances))

			for i, name in tqdme(instances, desc=desc):
				u = cdn.joinpath(f"{study_uid}/{series['series_number']}.{name}.dcm")
				async with client.get(u) as response:
					dir_.get(i, "dcm").write_bytes(await response.read())
