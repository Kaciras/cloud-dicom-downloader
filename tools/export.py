import argparse
import re
import typing
from hashlib import sha256
from pathlib import Path

import numpy as np
from PIL import Image
from moviepy import ImageClip, VideoFileClip, concatenate_videoclips
from proglog import TqdmProgressBarLogger
from pydicom import dcmread, pixels, Dataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, PYDICOM_ROOT_UID, generate_uid
from tqdm import tqdm

from crawlers._utils import SeriesDirectory

_moviepy_logger = TqdmProgressBarLogger(print_messages=False)

OUTPUT_DIR = Path("exports")
FPS = 10

VIDEO_CODECS = ("avi", "mp4", "ogv", "webm")
_DIGITS_RE = re.compile(r"\d+")


def _try_sort_numeric(values: list[Path]):
	"""
	尝试从文件名中找出数字，并按其排序，避免文件系统返回错误的顺序。
	如果有一个文件名不含数字则原样返回，否则返回排序后的列表。
	"""
	tuples = []
	for value in values:
		# 扩展名可能有数字（比如 .jp2）所以用 stem。
		# 应该没有像分卷压缩包那样把序号放最后的吧。
		match = _DIGITS_RE.search(value.stem)
		if not match:
			return values
		tuples.append((int(match.group(0)), value))
	tuples.sort()
	return [second for _, second in tuples]


def _get_slice_position(ds: Dataset):
	"""
	通过 ImagePositionPatient 和 ImageOrientationPatient 计算切面在扫描轴上的位置。
	原理就是对切面的三个坐标应用矩阵变换，结果等于 SliceLocation，但后者是可选标签不一定有。

	https://stackoverflow.com/a/6598664/7065321
	"""
	try:
		return ds.SliceLocation
	except AttributeError:
		position = np.array(ds.ImagePositionPatient)
		row, col = np.array(ds.ImageOrientationPatient).reshape(2, 3)
		return np.dot(np.cross(row, col), position)


class SliceList(list[np.ndarray]):
	"""
	DICOM 文件转换工具，支持 DCM 文件、图片、视频三者之间的转换。
	用法是先 from_* 读取，然后 to_* 输出即可。
	"""

	@staticmethod
	def from_video(file: Path, sample_fps=None):
		# moviepy 文件不存在的报错有点怪，还是自己检查吧。
		if not file.is_file():
			raise FileNotFoundError(file)
		clip = VideoFileClip(file)
		return SliceList(clip.iter_frames(sample_fps))

	@staticmethod
	def from_pictures(files: list[Path]):
		files = _try_sort_numeric(files)
		return SliceList(np.asarray(Image.open(file)) for file in files)

	@staticmethod
	def from_dcm_files(files: list[Path]):
		files, images = _try_sort_numeric(files), SliceList()

		datasets = typing.cast(list[Dataset], files)
		for i, file in enumerate(files):
			datasets[i] = dcmread(file)

		try:
			datasets.sort(key=_get_slice_position)
		except AttributeError:
			pass  # 可能是从图片转来的，没有位置标签。

		# https://github.com/ykuo2/dicom2jpg/blob/main/dicom2jpg/utils.py
		for ds in tqdm(datasets, "Loading", leave=False):
			px = ds.pixel_array
			px = pixels.apply_modality_lut(px, ds)
			px = pixels.apply_voi_lut(px, ds)
			px = pixels.apply_presentation_lut(px, ds)

			min_ = px.min()
			px = (px - min_) / (px.max() - min_) * 255

			images.append(px.astype(np.uint8))

		return images

	def to_video(self, out_file: Path, fps=FPS):
		"""
		保存影像序列为视频，编码将根据文件的扩展名决定，支持 avi、mp4、ogv、webm，其中 avi 是无损。

		:param fps: 帧率，默认每秒 10 张图
		:param out_file: 输出的视频文件名
		"""
		clips = [ImageClip(x, duration=1 / fps) for x in self]
		video = concatenate_videoclips(clips, method="compose")
		codec = "png" if out_file.suffix == ".avi" else None
		video.write_videofile(out_file, codec=codec, fps=fps, logger=_moviepy_logger)

	def to_pictures(self, save_to: Path, ext="png"):
		out_dir = SeriesDirectory(save_to, len(self), False)
		for i, px in enumerate(self):
			Image.fromarray(px).save(out_dir.get(i, ext))

	def to_dcm_files(self, save_to: Path, entropy: str = None):
		"""
		将影像序列保存为 DCM 文件，仅包含必要的标签，其中一些 UID 将自动生成。
		由于本类不含标签数据，做 DCM -> DCM 的转换会丢失标签信息。

		:param save_to: 要保存到的目录
		:param entropy: 种子字符串，用于生成稳定的 UID
		"""
		hasher, blobs = sha256(b"Kaciras DICOM Convertor"), []
		out_dir = SeriesDirectory(save_to, len(self), False)

		for px in self:
			buffer = px.tobytes()
			blobs.append(buffer)
			hasher.update(buffer)

		h64 = str(int.from_bytes(hasher.digest())).zfill(32)
		study_uid = generate_uid(entropy_srcs=[entropy] if entropy else None)
		series_uid = PYDICOM_ROOT_UID + h64[:32]

		for i, px in enumerate(self):
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


def main():
	parser = argparse.ArgumentParser(description="DICOM Convertor")
	parser.add_argument("format")
	parser.add_argument("source")
	parser.add_argument("-e", "--entropy")
	parser.add_argument("-ifps", type=int)
	parser.add_argument("-ofps", type=int)
	args = parser.parse_args()

	OUTPUT_DIR.mkdir(exist_ok=True)
	codec, source = args.format.lower(), Path(args.source)
	out_name = OUTPUT_DIR / source.name

	if source.is_file():
		slices = SliceList.from_video(source, args.ifps)
		out_name = out_name.with_suffix("")
	else:
		files = list(source.iterdir())
		if files[0].suffix == ".dcm":
			slices = SliceList.from_dcm_files(files)
		else:
			slices = SliceList.from_pictures(files)

	if codec == "dcm":
		slices.to_dcm_files(out_name, args.entropy, args.ss, args.ps)
	elif codec in Image.EXTENSION:
		slices.to_pictures(out_name, codec)
	elif codec in VIDEO_CODECS:
		name = out_name.name + "." + codec
		slices.to_video(OUTPUT_DIR / name, args.ofps)
	else:
		print(F"命令行参数存在错误，未知的输出格式：{codec}")


if __name__ == "__main__":
	main()

# moviepy 里头调用 ffmpeg 命令行工具，不指定路径的话它会自动下载一个。
# os.environ["FFMPEG_BINARY"] = r"D:\Program Files\ffmpeg\bin\ffmpeg.exe"
