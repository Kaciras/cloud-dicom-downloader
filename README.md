# cloud-dicom-downloader

医疗云影像爬虫，用于下载 CT、MRI 等片子的 DICOM 文件。目前仅支持两家，因为我只有两家的片子。

[[TOC]]

## 支持的站点

### qr.szjudianyun.com

不知道什么名字的系统，URL 格式为`http://qr.szjudianyun.com/<xxx>/?a=<hospital_id>&b=<study>&c=<password>`，可从报告单扫码得到。

运行该命令下载：

```
node src/szjudianyun.js <url>
```

### medicalimagecloud.com

海纳医信的云影像系统，URL 格式为`https://<xxx>.medicalimagecloud.com:<port?>/t/<32-chars-hex>`，还需要一个密码。

运行该命令安装依赖并下载：

```
pip install -r requirements.txt
python src/hinacom.py <url> <password>
```
