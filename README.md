# cloud-dicom-downloader

医疗云影像下载器，从在线报告下载 CT、MRI 等片子的 DICOM 文件。

> [!WARNING]
> 
> 由于没有时间，本项目不再更新，也不再免费帮下载片子；如要下载可联系 [contact@kaciras.com](mailto:contact@kaciras.com)，每次检查 50￥。
> 
> 下载须知：
> - 部分医院的系统复杂，需要较长的时间（数小时）才能爬取。
> - 少数系统不提供原始文件，无法下载，已知有：`锐珂 CareaStream`、`联众医疗 eImage`、`东软睿影 cloud film system`

关于下载的格式：

一个检查下包含多个目录，每目录对应一个序列，序列内每一个切面保存为一个`.dcm`扩展名结尾的 DICOM 文件，文件的结构为：
```text
[患者姓名]-[检查项目]-[时间]
|
├─── [序列名1]
|    |
|    ├── 00001.dcm
|    ├── 00002.dcm
|    └── ......
|
├─── [序列名2]
└─── ......
```
可以通过阅片软件或在线阅片网站来查看下载的文件，打开时选择某个序列或整个检查的文件夹即可。

* [使用步骤](#使用步骤)
* [支持的站点](#支持的站点)
  * [medicalimagecloud.com](#medicalimagecloudcom)
  * [mdmis.cq12320.cn](#mdmiscq12320cn)
  * [ylyyx.shdc.org.cn](#ylyyxshdcorgcn)
  * [zscloud.zs-hospital.sh.cn](#zs-hospitalshcn)
  * [ftimage.cn](#ftimagecn)
  * [qr.szjudianyun.com](#qrszjudianyuncom)
  * [ss.mtywcloud.com](#ssmtywcloudcom)
  * [m.yzhcloud.com](#myzhcloudcom)
  * [work.sugh.net](#worksughnet)

## 使用步骤

- 先确保您的报告链接是有效的，能够通过浏览器访问，没有过期。
- 本项目需要 Python 来运行，没有就去 [https://www.python.org](https://www.python.org/downloads) 下载并安装。
- 克隆代码（不会的可以点击右上角的 Code -> Download ZIP，然后解压）。
- 进入解压后的目录，运行命令行（右键 -> 在终端中打开）。
- 输入`pip install -r requirements.txt`并按回车键。
- 等待运行完成，然后根据要下载的网站，选择下面一节中的的命令运行。

## 支持的站点

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

上海申康医院发展中心的在线影像查看器，URL 格式支持以下两种：

- `https://ylyyx.shdc.org.cn/#/home?sid=<number>&token=<hex>`
- `https://ylyyx.shdc.org.cn/code.html?appid=<xxx>&share_id=<uuid>&ctype=5`

```
python downloader.py <url>
```

### zs-hospital.sh.cn

复旦大学附属中山医院所使用的影像平台，URL 格式为`https://zscloud.zs-hospital.sh.cn/film/#/shared?code=<code>`。

```
python downloader.py <url>
```

### ftimage.cn

飞图影像的医疗云影像平台，支持以下两种链接：

- `https://yyx.ftimage.cn/dimage/index.html?stm=<一长串>`
- `https://app.ftimage.cn/dimage/index.html?accessionNumber=<hex>&hsCode=<number>&date=<number>`

```
python downloader.py <url>
```

该爬虫依赖浏览器，在 Windows 上默认使用 Edge，如果启动失败请尝试运行`playwright install`改用捆绑的浏览器。

### qr.szjudianyun.com

URL 格式为`http://qr.szjudianyun.com/<xxx>/?a=<hospital_id>&b=<study>&c=<password>`，可从报告单扫码得到。

```
python downloader.py <url>
```

### ss.mtywcloud.com

明天医网的移动影像处理工作站，URL 格式为`https://ss.mtywcloud.com/ICCWebClient/Image/Viewer?AllowQuery=0&DicomDirPath=<URL>&OrganizationID=xxx&Anonymous=true&Token=xxx`。

```
python downloader.py <url>
```

### m.yzhcloud.com

URL 格式为`https://m.yzhcloud.com/w_viewer_2/?study_instance_uid=xxx&org_id=xxx`

```
python downloader.py <url>
```

### work.sugh.net

URL 格式为`https://work.sugh.net:8002/pc/auth-viewer?clinicalShareToken=<token>`

```
python downloader.py <url>
```
