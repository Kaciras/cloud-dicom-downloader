"""
DCM 文件转换工具，支持导出为图片或视频。
TODO: 匿名化
"""
from moviepy import ImageClip, VideoFileClip, concatenate_videoclips
import os
from pathlib import Path
import numpy as np
from pydicom import dcmread, pixels, Dataset
from PIL import Image
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, PYDICOM_ROOT_UID, UID
from hashlib import sha256

os.environ["FFMPEG_BINARY"] = r"D:\Program Files\ffmpeg\bin\ffmpeg.exe"

OUTPUT_DIR = Path("exports")
FPS = 10

def images_to_video(images: list[np.array], out_file: Path):
	clips = [ImageClip(x, duration=1 / FPS) for x in images]
	video = concatenate_videoclips(clips, method="compose")

	if out_file.suffix != ".avi":
		video.write_videofile(out_file, fps=FPS)
	else:
		video.write_videofile(out_file, codec="png", fps=FPS)

	print("Video created successfully:", out_file)


def video_to_images(file: Path, sample_fps=None):
	return list(VideoFileClip(file).iter_frames(sample_fps))


def load_series_images(directory: Path):
	files = os.listdir(directory)
	images = [None] * len(files)
	
	# https://github.com/ykuo2/dicom2jpg/blob/main/dicom2jpg/utils.py
	for file in files:
		ds = dcmread(image_dir / file)
		i, px = ds.InstanceNumber, ds.pixel_array
		
		px = pixels.apply_modality_lut(px, ds)
		px = pixels.apply_voi_lut(px, ds)
		px = pixels.apply_presentation_lut(px, ds)
		
		px = ((px-px.min())/(px.max()-px.min())) * 255
		
		images[i - 1] = px.astype(np.uint8)

	return images


def _save_dcms(images: list[np.array], directory: Path):
	hasher, blobs = sha256(b"Kaciras DICOM Convertor"), []

	for px in images:
		buffer = px.tobytes()
		hasher.update(buffer)
		blobs.append(buffer)

	hash = str(int.from_bytes(hasher.digest()))
	prefix = PYDICOM_ROOT_UID + hash[:24].zfill(24)

	for i, px in enumerate(images):
		ds = Dataset()
		ds.ensure_file_meta()

		ds.SOPClassUID = SecondaryCaptureImageStorage
		ds.SOPInstanceUID = UID(prefix + str(i))
	
		ds.BitsAllocated = 8
		ds.BitsStored = 8
		ds.HighBit = ds.BitsStored - 1
		ds.PixelRepresentation = 0
		ds.SamplesPerPixel = 1
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


def save_images(images: list[np.array], directory: Path, ext = "png"):
	directory.mkdir(exist_ok=True)

	if ext == "dcm":
		return _save_dcms(images, directory)

	for i, px in enumerate(images):
		Image.fromarray(px).save(directory / f"{i}.{ext}")


if __name__ == "__main__":
	image_dir = Path(r"download\test.avi")
	
	# images = load_series_images(image_dir)
	# images_to_video(images, image_dir.with_suffix(".avi"))

	images = video_to_images(image_dir)
	save_images(images, Path("exports"), "dcm")

