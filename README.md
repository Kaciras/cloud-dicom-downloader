# cloud-dicom-downloader

医疗云影像下载器，从在线报告下载 CT、MRI 等片子的 DICOM 文件。

目前仅支持两家，因为我只有两家的片子，如果需要支持其它网站请见[开发](#开发)。

* [安装](#安装)
* [支持的站点](#支持的站点)
  * [qr.szjudianyun.com](#qrszjudianyuncom)
  * [medicalimagecloud.com](#medicalimagecloudcom)
* [开发](#开发)

## 安装

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

海纳医信的云影像系统，URL 格式为`https://*.medicalimagecloud.com:<port?>/t/<32-chars-hex>`，还需要一个密码。

```
python downloader.py <url> <password> [--raw]
```

`--raw` 如果指定该参数，则下载像素数据，默认下载 JPEG2000 无损压缩的图像。

> [!WARNING]
> 由于未能下载到标签的类型信息，所有私有标签将保存为`LO`类型。

## 开发

由于爬虫无法只靠本机调试，如有问题请提 Issue 或 Pull Request，并附带报告的地址和密码（如果有），报告不会被用于开发本项目之外的目的。
