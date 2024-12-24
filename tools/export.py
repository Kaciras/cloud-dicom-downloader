"""
DCM 文件转换工具，支持导出为图片或视频。
TODO: 匿名化，反向转换
"""
from moviepy import ImageClip, concatenate_videoclips
import os
import re
from pathlib import Path
import numpy as np
from pydicom import dcmread, pixels

os.environ["FFMPEG_BINARY"] = r"D:\Program Files\ffmpeg\bin\ffmpeg.exe"

def images_to_video(images: list[np.array]):
    clips = [ImageClip(x, duration=0.1) for x in images]
    video = concatenate_videoclips(clips, method="compose")
    video.write_videofile("test.mp4",  fps=30)
    print("Video created successfully:", "test.avi")

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
        
        px = ((px-px.min())/(px.max()-px.min())) * 255.0
        
        images[i - 1] = px.astype(np.uint8)

    return images
    
if __name__ == "__main__":
    image_dir = Path(r"download\test")
    
    images = load_series_images(image_dir)
    images_to_video(images)
