import os
import re
from hashlib import sha256
from pathlib import Path

import numpy as np
from PIL import Image
from moviepy import ImageClip, VideoFileClip, concatenate_videoclips
from pydicom import dcmread, pixels, Dataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, PYDICOM_ROOT_UID, generate_uid
from tqdm import tqdm

from crawlers._utils import SeriesDirectory

# moviepy 里头调用 ffmpeg 命令行工具，不指定路径的话也会自动下载一个。
os.environ["FFMPEG_BINARY"] = r"D:\Program Files\ffmpeg\bin\ffmpeg.exe"

OUTPUT_DIR = Path("exports")
FPS = 10
DIGITS_RE = re.compile(r"\d+")


def _try_sort_numeric(values: list[Path]):
	"""
	尝试从文件名中找出数字，并按其排序，避免文件系统返回错误的顺序。

	:return: 如果有一个文件名中没数字则原样返回，否则返回排序后的列表。
	"""
	tuples = []
	for value in values:
		match = DIGITS_RE.search(value.name)
		if not match:
			return values
		tuples.append((int(match.group(0)), value))
	tuples.sort()
	return list(second for _, second in tuples)


class SeriesImageList:
	"""
	DICOM 文件转换工具，支持 DCM 文件、图片、视频三者之间的转换。
	用法是先 from_* 读取，然后 to_* 输出即可。
	"""

	name: str
	images: list[np.ndarray]

	def __init__(self, name: str, images: list[np.ndarray]):
		self.name = name
		self.images = images

	@staticmethod
	def from_video(file: Path, sample_fps=None):
		# moviepy 文件不存在的报错有点怪，还是自己检查吧。
		if not file.is_file():
			raise FileNotFoundError(file)
		frames = VideoFileClip(file).iter_frames(sample_fps)
		return SeriesImageList(file.name, list(frames))

	@staticmethod
	def from_pictures(name: str, files: list[Path]):
		images = [None] * len(files)

		for i, file in enumerate(_try_sort_numeric(files)):
			image = Image.open(file)
			images[i] = np.asarray(image)

		return SeriesImageList(name, images)

	@staticmethod
	def from_dcm_files(name: str, files: list[Path]):
		images = [None] * len(files)
		files = _try_sort_numeric(files)

		# https://github.com/ykuo2/dicom2jpg/blob/main/dicom2jpg/utils.py
		for file in tqdm(files, "Loading"):
			ds = dcmread(file)
			k, px = ds.InstanceNumber, ds.pixel_array

			px = pixels.apply_modality_lut(px, ds)
			px = pixels.apply_voi_lut(px, ds)
			px = pixels.apply_presentation_lut(px, ds)

			min_ = px.min()
			px = (px - min_) / (px.max() - min_) * 255

			images[k - 1] = px.astype(np.uint8)

		return SeriesImageList(name, images)

	def to_video(self, out_file: Path):
		clips = [ImageClip(x, duration=1 / FPS) for x in self.images]
		video = concatenate_videoclips(clips, method="compose")

		if out_file.suffix != ".avi":
			video.write_videofile(out_file, fps=FPS)
		else:
			video.write_videofile(out_file, codec="png", fps=FPS)

	def to_pictures(self, save_to: Path, ext="png"):
		out_dir = SeriesDirectory(save_to, len(self.images), False)
		for i, px in enumerate(self.images):
			Image.fromarray(px).save(out_dir.get(i, ext))

	def to_dcm_files(self, save_to: Path, entropy=None):
		hasher, blobs = sha256(b"Kaciras DICOM Convertor"), []
		out_dir = SeriesDirectory(save_to, len(blobs), False)

		for px in self.images:
			buffer = px.tobytes()
			blobs.append(buffer)
			hasher.update(buffer)

		h64 = str(int.from_bytes(hasher.digest()))
		study_uid = generate_uid(entropy_srcs=[entropy] if entropy else None)
		series_uid = PYDICOM_ROOT_UID + h64.zfill(32)

		for i, px in enumerate(self.images):
			ds = Dataset()
			ds.ensure_file_meta()

			ds.SOPClassUID = SecondaryCaptureImageStorage
			ds.StudyInstanceUID = study_uid
			ds.SeriesInstanceUID = series_uid
			ds.SOPInstanceUID = series_uid[:50] + str(i)

			ds.BitsAllocated = 8
			ds.BitsStored = 8
			ds.HighBit = ds.BitsStored - 1
			ds.PixelRepresentation = 0
			ds.SamplesPerPixel = 1
			ds.NumberOfFrames = 1
			ds.Rows = px.shape[0]
			ds.Columns = px.shape[1]
			ds.PixelData = blobs[i]

			if px.shape[2] == 3:
				ds.PhotometricInterpretation = "RGB"
				ds.PlanarConfiguration = 0
			else:
				ds.PhotometricInterpretation = "MONOCHROME1"

			ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
			ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
			ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID

			ds.save_as(out_dir.get(i, "dcm"), enforce_file_format=True)
