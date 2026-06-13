# E-House Model

Semi-automatic geometry extraction tooling for E-House steel frame modeling.

Current implementation focuses on the early geometry pipeline:

- project.yaml loading
- 2D/3D node and member data models
- single-face DXF centerline candidate extraction
- base-face snap/extend and top-left origin normalization
- plane-local 2D to global 3D coordinate mapping
- face_model.json and overlay.dxf output
- global_model.json and geometry.std output
- nodes.csv and members.csv export

The current GUI is a simplified Chinese base-only workflow for engineering
debugging.

## 底座 GUI

PyCharm 中直接运行：

```text
run_gui.py
```

第一版 GUI 只处理底座：

- 选择底座 DXF
- 识别中心线
- 按构件宽度自动吸附/延伸中心线端点
- 以左上角中心线交点为原点
- 在节点表中修改 X/Z 坐标，单位为米，保留 4 位小数
- 预览图实时刷新
- 导出 `geometry.std`，使用 `UNIT METER KN`

GUI 中的 `最大配对宽度(m)` 和 `最大延伸上限(m)` 按米输入；DXF 内部识别仍按图纸原始毫米坐标计算。

PySide6 使用已验证可工作的 6.8 系列：

```powershell
& 'D:\Users\Administrator\anaconda3\python.exe' -m pip install PySide6==6.8.3
```

如果 QtCore 报 `DLL load failed`，先检查是否能独立导入：

```powershell
& 'D:\Users\Administrator\anaconda3\python.exe' -c "from PySide6 import QtCore; print(QtCore.qVersion())"
```

本机曾出现过旧版 `*.cp313-win_amd64.pyd` 残留，Python 会优先加载这些文件，导致它们和当前 PySide6 DLL 不匹配。修复方式是把这些旧文件移出 `D:\Users\Administrator\anaconda3\Lib\site-packages\PySide6` 和 `...\shiboken6`。

## Extract one face

PyCharm debug entry:

Run `run_face_extractor.py` from the project root and follow the prompts.

Command-line equivalent:

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
& 'D:\Users\Administrator\anaconda3\python.exe' -m ehouse_model.face_extractor drawings/front.dxf
```

By default this writes `face_model.json`, `warnings.csv`, and `centerline_overlay.dxf`
in the current directory.

## Build a global model

PyCharm debug entry:

Run `run_global_builder.py` from the project root and follow the prompts. If
`project.json` does not exist yet, the script can create a one-face starter
project from `output/face_model.json`.
