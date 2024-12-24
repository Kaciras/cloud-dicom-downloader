"""
DCM 文件转换工具，支持导出为图片或视频。
TODO: 匿名化，反向转换
"""
from moviepy import ImageClip, VideoFileClip, concatenate_videoclips
import os
from pathlib import Path
import numpy as np
from pydicom import dcmread, pixels
from PIL import Image

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


def video_to_images(file: Path):
	video = VideoFileClip(file)


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


def convert_all():pass

if __name__ == "__main__":
	image_dir = Path(r"download\test")
	
	images = load_series_images(image_dir)
	images_to_video(images, image_dir.with_suffix(".avi"))
