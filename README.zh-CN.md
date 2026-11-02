<p align="center"><img src="openvelox/resources/logo.png" width="120"></p>

# OpenVelox

[English](README.md) · 许可证：GPL-3.0

OpenVelox 是一款免费开源的电镜数据分析软件，界面和功能参照 Thermo Fisher Velox，用于查看和分析 TEM/STEM 数据。

**支持格式：** Velox `.emd`（含 EDS SpectrumStream）、TIA `.ser/.emi`、DigitalMicrograph `.dm3/.dm4`、TIFF。

**主要功能：** 图像显示与对比度/色表、多窗格联动、元数据查看、FFT 掩模与晶面间距、滤波与背底扣除、漂移校正叠加（DCFI）、测量标注与带比例尺导出、EDS 寻峰 / Cliff-Lorimer 定量 / 面分布 / 线扫、4D-STEM 虚拟 BF/ADF/ABF、质心/DPC/iDPC、报告导出（PDF/HTML/PPTX）、会话保存。

## 一键安装

1. 在 [Releases](https://github.com/xinren1230/OpenVelox/releases/latest) 下载 **OpenVelox-Setup-0.5.0.exe**。
2. 双击按提示安装，不需要 Python，也不需要管理员权限。
3. 从开始菜单或桌面打开 OpenVelox，把数据文件拖进窗口即可。

## 快速上手

- **打开文件：** `Ctrl+O` 或直接拖入；在实验浏览器里双击条目查看。
- **测量：** `L` 线剖面，`D` 距离，`R` 区域；`Esc` 回到指针。
- **FFT：** `Ctrl+F`，画掩模后做逆 FFT；点两个斑点得到 d 值。
- **EDS：** 打开能谱面扫，选元素和背底模型，读取 wt.%/at.%，显示元素分布图。
- **导出：** `Ctrl+E` 导出带比例尺的图像，`Ctrl+Shift+R` 导出报告。

日志位于 `%LOCALAPPDATA%\OpenVelox\logs`，提 issue 时请附上。

## 从源码运行

```
pip install -r requirements.txt
python -m openvelox
```
