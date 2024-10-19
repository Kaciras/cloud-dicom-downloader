# cloud-dicom-downloader

医疗云影像爬虫，用于下载 CT、MRI 等片子的 DICOM 文件。目前仅支持两家，因为我只有两家的片子。

[[TOC]]

## 用法

请先确保安装了 Python >= 12，然后安装依赖：

```
pip install -r requirements.txt
```

根据网站的不同，运行所需的参数也不一样，具体见下面支持的站点。

## 支持的站点

### qr.szjudianyun.com

不知道什么名字的系统，URL 格式为`http://qr.szjudianyun.com/<xxx>/?a=<hospital_id>&b=<study>&c=<password>`，可从报告单扫码得到。

```
python downloader.py <url>
```

### medicalimagecloud.com

海纳医信的云影像系统，URL 格式为`https://<xxx>.medicalimagecloud.com:<port?>/t/<32-chars-hex>`，还需要一个密码。

```
python downloader.py <url> <password> [--j2k]
```

`--j2k` 如果指定该参数，则下载 JPEG2000 无损压缩的图像，没有则下载像素数据。
