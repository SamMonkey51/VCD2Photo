# VCD Wave Image Tool

把 VCD 波形转换为适合实验报告、课程设计报告和文档插图使用的 PNG/SVG/PDF。

## 快速开始

先检查依赖：

```sh
which python3
which rsvg-convert
which npx || which wavedrom-cli
```

查看 VCD 信息：

```sh
./vcd-to-image info --vcd examples/lab1_led_test.vcd
```

生成一张 Vivado 深色风格波形图：

```sh
./vcd-to-image \
  --vcd examples/lab1_led_test.vcd \
  --output out/lab1_led_test \
  --title "Lab1 LED流水灯" \
  --theme vivado-dark \
  --range 0ns..310ns \
  --format png,svg,pdf,json \
  --signal tb_led_test.sys_clk:bit \
  --signal tb_led_test.rst_n:bit \
  --signal 'timer=tb_led_test.dut.timer[31:0]:bus' \
  --signal 'led[3:0]=tb_led_test.led[3:0]:bus'
```

使用配置文件批量生成：

```sh
./vcd-to-image --config examples/report_waves.json
```

## 常用功能

- `info`: 列出 timescale、时间跨度、信号路径、位宽、事件数和 alias 数量
- `--signal`: 手动选择信号，支持 `path`、`label=path`、`label=path:kind`
- `--signals-file`: 从文本文件读取信号列表
- `--match` / `--scope` / `--exclude`: 自动选择信号
- `--range` / `--start` / `--end`: 选择时间范围，支持 tick、`ps`、`ns`、`us`、`ms`
- `--theme`: `vivado-dark`、`vivado-light`、`report-light`、`report-dark`、`monochrome`、`wavedrom`
- `--format`: `png`、`svg`、`pdf`、`json`、`all`
- `--value-format`: 总线值显示为 `hex`、`bin`、`dec` 或 `raw`
- `--hide-data-labels`: 高密度图隐藏总线值文本
- `--page-size`: 多信号图自动分页，输出 `_p01`、`_p02`
- `--label-strip-prefix` / `--label-replace`: 批量清理长层级变量名
- `--png-scale` / `--png-width` / `--png-height` / `--dpi` / `--background`: 控制导出尺寸和背景
- `--theme-color`: 覆盖主题颜色，例如 `--theme-color signal=#00ff88`
- `--strict`: 批量生成时遇到信号缺失或歧义直接失败
- `--dry-run`: 只打印选择结果，不生成图片

## 依赖

Python 只使用标准库。外部命令依赖：

- `rsvg-convert`: 把 SVG 转为 PNG/PDF，Ubuntu/Debian 可安装 `librsvg2-bin`
- `wavedrom-cli` 或可运行 `npx --yes wavedrom-cli` 的 Node.js/npm 环境

Ubuntu/Debian 示例：

```sh
sudo apt-get install -y librsvg2-bin nodejs npm
```

## 目录结构

```text
.
├── README.md
├── vcd-to-image
├── examples/
│   ├── lab1_led_test.vcd
│   ├── report_waves.json
│   └── signals.txt
└── tools/
    ├── vcd_to_image.py
    └── vivado_wave.py
```

生成的文件默认放在 `out/`，该目录已加入 `.gitignore`。
