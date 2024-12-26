"""
DCM 文件转换工具，支持 DCM 文件、图片和视频之间的转换。
"""
import os
from hashlib import sha256
from pathlib import Path

import numpy as np
from PIL import Image
from moviepy import ImageClip, VideoFileClip, concatenate_videoclips
from pydicom import dcmread, pixels, Dataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, PYDICOM_ROOT_UID

# moviepy 里头调用 ffmpeg 命令行工具，不指定路径的话也会自动下载一个。
os.environ["FFMPEG_BINARY"] = r"D:\Program Files\ffmpeg\bin\ffmpeg.exe"

OUTPUT_DIR = Path("exports")
FPS = 10


class SeriesImageList:
	"""

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

		for i, file in enumerate(files):
			image = Image.open(file)
			images[i] = np.asarray(image)

		return SeriesImageList(name, images)

	@staticmethod
	def from_dcm_files(name: str, files: list[Path]):
		images = [None] * len(files)

		# https://github.com/ykuo2/dicom2jpg/blob/main/dicom2jpg/utils.py
		for i, file in enumerate(files):
			ds = dcmread(file)
			i, px = ds.InstanceNumber, ds.pixel_array

			px = pixels.apply_modality_lut(px, ds)
			px = pixels.apply_voi_lut(px, ds)
			px = pixels.apply_presentation_lut(px, ds)

			min_ = px.min()
			px = (px - min_) / (px.max() - min_) * 255

			images[i - 1] = px.astype(np.uint8)

		return SeriesImageList(name, images)

	def to_video(self, out_file: Path):
		clips = [ImageClip(x, duration=1 / FPS) for x in self.images]
		video = concatenate_videoclips(clips, method="compose")

		if out_file.suffix != ".avi":
			video.write_videofile(out_file, fps=FPS)
		else:
			video.write_videofile(out_file, codec="png", fps=FPS)

	def to_pictures(self, directory: Path, ext="png"):
		directory.mkdir(exist_ok=True)
		for i, px in enumerate(self.images):
			Image.fromarray(px).save(directory / f"{i}.{ext}")

	def to_dcm_files(self, directory: Path):
		hasher, blobs = sha256(b"Kaciras DICOM Convertor"), []

		for px in self.images:
			buffer = px.tobytes()
			hasher.update(buffer)
			blobs.append(buffer)

		h64 = str(int.from_bytes(hasher.digest()))
		prefix = PYDICOM_ROOT_UID + h64[:24].zfill(24)

		for i, px in enumerate(self.images):
			ds = Dataset()
			ds.ensure_file_meta()

			ds.SOPClassUID = SecondaryCaptureImageStorage
			ds.SOPInstanceUID = prefix + str(i)
			ds.StudyInstanceUID = "1.2.3.4"
			ds.SeriesInstanceUID = "3.23.53.4666"

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

			ds.save_as(directory / f"{i}.dcm", enforce_file_format=True)
