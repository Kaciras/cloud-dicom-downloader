from pathlib import Path

from pydicom import dcmread, dcmwrite


def set_window(series: Path, center, width):
	for file in series.iterdir():
		ds = dcmread(file)
		ds.WindowCenter = center
		ds.WindowWidth = width
		dcmwrite(file, ds, enforce_file_format=True)


if __name__ == "__main__":
	set_window(Path("TODO"), 60, 1500)
