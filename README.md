# cloud-dicom-downloader

医疗云影像下载器，从在线报告下载 CT、MRI 等片子的 DICOM 文件。

* [安装](#安装)
* [支持的站点](#支持的站点)
  * [qr.szjudianyun.com](#qrszjudianyuncom)
  * [medicalimagecloud.com](#medicalimagecloudcom)
  * [mdmis.cq12320.cn](#mdmiscq12320cn)
  * [ylyyx.shdc.org.cn](#ylyyxshdcorgcn)
  * [zscloud.zs-hospital.sh.cn](#zs-hospitalshcn)
* [开发](#开发)

## 安装

- 请先确保安装了 Python，如果没有则去 [https://www.python.org](https://www.python.org/downloads) 下载并安装。
- 下载本项目（不会的可以点击右上角的 Code -> Download ZIP，然后解压）。
- 进入解压后的目录，运行命令行（右键 -> 在终端中打开）。
- 输入`pip install -r requirements.txt`并按回车键。
- 等待运行完成，然后根据要下载的网站，选择下面一节中的的命令运行。

## 支持的站点

### qr.szjudianyun.com

URL 格式为`http://qr.szjudianyun.com/<xxx>/?a=<hospital_id>&b=<study>&c=<password>`，可从报告单扫码得到。

```
python downloader.py <url>
```

### medicalimagecloud.com

海纳医信的云影像，URL 格式为`https://*.medicalimagecloud.com:<port?>/t/<hex>`，还需要一个密码。

```
python downloader.py <url> <password> [--raw]
```

`--raw` 如果指定该参数，则下载未压缩的像素，默认下载 JPEG2000 无损压缩的图像。

> [!WARNING]
> 由于未能下载到标签的类型信息，所有私有标签将保存为`LO`类型。

### mdmis.cq12320.cn

重庆卫健委在线报告查看网站，其中的影像查看器也是海纳医信。

URL 格式：`https://mdmis.cq12320.cn/wcs1/mdmis-app/h5/#/share/detail?share_id=<hex>&content=<token>&channel=share`

命令用法与注意事项跟`medicalimagecloud.com`相同，但不需要密码。

### ylyyx.shdc.org.cn

上海申康医院发展中心的在线影像查看器，URL 格式为`https://ylyyx.shdc.org.cn/#/home?sid=<number>&token=<hex>`。

```
python downloader.py <url>
```

### zs-hospital.sh.cn

复旦大学附属中山医院所使用的影像平台，URL 格式为`https://zscloud.zs-hospital.sh.cn/film/#/shared?code=<code>`。

```
python downloader.py <url>
```
