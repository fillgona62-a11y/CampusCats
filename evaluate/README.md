# 用本校照片检验候选识别

请一位熟悉校园猫的人给照片标上身份，把不同日期拍到的同一只猫放在同一编号下。每只可以先收集 3～5 张，涵盖正脸、侧身或尾部的稳定特征。挑几只外观相似的猫，也留几只从未进入参考图库的猫。品种只在有可核查的来源材料时登记。

## 准备参考照和测试照

已在 App 确认过多日目击的学校，可以直接从已有记录导出清单，在项目根目录执行以下命令。将数据目录换成服务端实际使用的位置。导出使用已审核的猫编号，把一部分猫全部留作新猫测试，并排除将同时出现在建档组和测试组的同框照片。导出的图片路径仅供维护者在本地使用，清单保存在指定的新文件中。

```shell
python evaluate/export_reviewed.py --data-dir ./data --out photos.csv
```

如果你在 App 外整理样本，可以复制 [清单模板](manifest.example.csv)，改为 `photos.csv`。模板中的编号、日期和文件名都只是填表示例。把照片路径写成相对于清单的位置。`gallery` 表示建档参考照，`test` 表示模型第一次看到的测试照。

同一只猫的参考照和测试照应来自不同日期。连拍、转发、重新裁剪的同一张照片放在同一组。每一行标记一只猫。取景框的 `x`、`y` 是左上角，`width`、`height` 是宽和高，四项都按已纠正方向的照片宽高换算成 0～1 的比例。裁好的单猫照片可以填 `0,0,1,1`。

## 运行复测

在项目根目录、安装过服务端依赖的 Python 环境里运行以下命令。把两个路径换成你的清单位置和希望保存报告的位置。

```shell
python evaluate/run.py photos.csv --out report.json
```

在 `report.json` 里同时看样本数、猫的只数和以下指标。工具会检查原图像素重复、取景框重复以及同一只猫建档与测试日期重合。重新压缩的转发图和多次拍摄的近似图还需要整理者人工排除。

| 报告字段 | 如何解读 |
| --- | --- |
| `known_top1`、`known_top3` | 已建档猫的测试照片里，正确身份排第一或进入前三的比例。照片质量不足、未出现候选也计入分母 |
| `unknown_given_any_candidate` | 从未建档的猫被列出任何旧猫候选的比例。值高时，维护者需要花更多时间排除错误候选 |
| `quality_abstentions` | 因清晰度、曝光或框内像素不足而放弃推荐的照片占比。可以查看对应原图，判断提示是否恰当 |

某类没有测试照片时，相应比率显示 `null`。调整候选阈值时，另留一批未参与调参的照片用于最终复测。给有相似花色的猫再单独整理一份清单，可以发现总体指标掩盖的混淆。

## 在现有服务上更换图像编码器

默认检索比较框内花色、明暗分布和纹理。正脸提示使用随项目提供的 Joseph Howse 正脸检测器，其许可附在模型 XML 内。侧身照也可参加检索。能否确认身份，由审核者结合已知档案判断。

图像数量增加时，可在服务端 Python 环境中安装 `opencv-python-headless`，使用编译后的 OpenCV 运行同一正脸检测器。这个选项只影响取景提示的执行方式。

如需比较预训练图像特征与默认检索，可以在能访问 Hugging Face 的机器上获取公开的 DINOv2-small ONNX 转换版。下载工具固定仓库提交并校验文件的 SHA-256，成功后会打印路径、来源、提交号和校验值。复现实验时可用 `--revision` 指定报告中记下的提交号。该模型的校内个体识别效果需要独立评测。[原始模型](https://huggingface.co/facebook/dinov2-small) · [ONNX 转换仓库](https://huggingface.co/Xenova/dinov2-small)

在 PowerShell 的服务端 Python 环境中运行以下命令。下载目录可以换成你希望保存模型的位置。

```powershell
python -m pip install onnxruntime
$modelInfo = python evaluate/get_encoder.py --dest ./models | ConvertFrom-Json
if (-not $modelInfo.path) { throw '未取得模型，请检查下载结果。' }
$env:CAMPUSCATS_ENCODER = $modelInfo.path
python evaluate/run.py photos.csv --out encoder-report.json
```

工具用模型文件的 SHA-256 标记版本。示例阈值应通过校内数据验证。可用 `--threshold` 对独立的调参照片试不同阈值，通过 `CAMPUSCATS_DISTANCE` 给在线服务设置选定值。确定切换后，关闭服务，用相同的环境变量运行以下命令，然后重新启动服务。`--data-dir` 对应启动服务使用的数据目录。单独配置了本地媒体目录时追加 `--media-dir`。如果采用分机图片存储，先把保留完整文件名的原图同步到本地媒体目录。

```powershell
python evaluate/reindex.py --data-dir ./data
```

重建工具从照片和取景框计算新特征，跳过已有同版本的记录。如果缺少原图或编码失败，本次更改整批回滚，可以补齐照片后重试。
