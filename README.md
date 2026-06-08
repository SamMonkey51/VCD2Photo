# VCD2Photo

VCD2Photo 是一个命令行工具，用来把 Verilog/VHDL 仿真产生的 VCD 波形转换成适合实验报告、课程设计报告和文档插图使用的图片。

支持输出：

- `png`: 适合 Word、WPS、PDF 报告插图
- `svg`: 矢量图，适合后期排版和缩放
- `pdf`: 可直接作为论文/报告图形
- `json`: WaveDrom 中间数据，便于调试或复用

默认主题 `vivado-dark` 尽量模拟 Vivado 深色波形窗口风格，也支持浅色报告、深色报告、单色打印和 WaveDrom 原始风格。

## 功能特性

- 读取 VCD 元信息：`timescale`、时间跨度、信号路径、位宽、事件数、alias 数量
- 支持手动选信号、信号列表文件、正则匹配、scope 自动选择
- 支持 VCD tick 和 `ps`、`ns`、`us`、`ms` 等人类可读时间单位
- 支持总线值按 `hex`、`bin`、`dec`、`raw` 显示
- 一条命令同时生成 PNG/SVG/PDF/JSON
- 多信号图可自动分页，避免报告图片重叠
- 可批量清理长层级变量名
- 可覆盖主题颜色，方便适配报告风格
- 支持 JSON 配置文件批量生成多张图

## 目录结构

```text
.
├── README.md
├── vcd-to-image                 # 便捷命令入口
├── vcd-mcp                      # Linux/macOS MCP stdio server 入口
├── vcd-mcp.bat                  # Windows MCP stdio server 入口
├── vcd-to-image.bat             # Windows CLI 入口
├── examples/
│   ├── lab1_led_test.vcd         # 示例 VCD
│   ├── report_waves.json         # 批量生成配置示例
│   ├── mcp-config-linux.json     # MCP 客户端 Linux/macOS 配置示例
│   ├── mcp-config-windows.json   # MCP 客户端 Windows 配置示例
│   └── signals.txt               # 信号列表示例
└── tools/
    ├── vcd_mcp_server.py         # MCP stdio server
    ├── vcd_to_image.py           # 主命令行工具
    └── vivado_wave.py            # VCD 解析和 WaveDrom 渲染库
```

生成结果默认放到 `out/` 目录，该目录已经加入 `.gitignore`。

## 安装依赖

Python 部分只使用标准库，不需要安装第三方 Python 包。

需要的外部命令：

- `rsvg-convert`: 把 SVG 转换为 PNG/PDF
- `wavedrom-cli`，或可运行 `npx --yes wavedrom-cli` 的 Node.js/npm 环境

### Ubuntu / Debian / WSL

```sh
sudo apt-get update
sudo apt-get install -y python3 librsvg2-bin nodejs npm
```

可选：全局安装 WaveDrom CLI，提高首次运行速度：

```sh
sudo npm install -g wavedrom-cli
```

全局安装不是必须的。如果没有找到 `wavedrom-cli`，工具会自动退回到：

```sh
npx --yes wavedrom-cli
```

### Fedora

```sh
sudo dnf install -y python3 librsvg2-tools nodejs npm
```

可选：

```sh
sudo npm install -g wavedrom-cli
```

### Arch Linux

```sh
sudo pacman -S --needed python librsvg nodejs npm
```

可选：

```sh
sudo npm install -g wavedrom-cli
```

### macOS

先安装 Homebrew，然后执行：

```sh
brew install python librsvg node
```

可选：

```sh
npm install -g wavedrom-cli
```

### 检查依赖是否可用

在项目根目录执行：

```sh
python3 --version
rsvg-convert --version
npx --yes wavedrom-cli --help >/dev/null
```

也可以检查命令路径：

```sh
which python3
which rsvg-convert
which wavedrom-cli || which npx
```

## 获取项目

```sh
git clone git@github.com:SamMonkey51/VCD2Photo.git
cd VCD2Photo
```

确保入口脚本有执行权限：

```sh
chmod +x vcd-to-image vcd-mcp
```

运行内置示例：

```sh
./vcd-to-image info --vcd examples/lab1_led_test.vcd
```

正常情况下会看到类似输出：

```text
timescale: 1ps
span: 0..310000 ticks
signals: 8 paths
```

## 基本调用方式

### 1. 查看 VCD 信息

```sh
./vcd-to-image info --vcd examples/lab1_led_test.vcd
```

只显示有事件的信号：

```sh
./vcd-to-image info \
  --vcd examples/lab1_led_test.vcd \
  --active-only
```

用正则筛选信号：

```sh
./vcd-to-image info \
  --vcd examples/lab1_led_test.vcd \
  --match 'timer|led|clk'
```

输出 JSON 元信息：

```sh
./vcd-to-image info \
  --vcd examples/lab1_led_test.vcd \
  --json
```

### 2. 生成一张波形图

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

这条命令会生成：

```text
out/lab1_led_test.png
out/lab1_led_test.svg
out/lab1_led_test.pdf
out/lab1_led_test.json
```

注意：信号参数里如果有总线下标，例如 `[3:0]`，建议加引号，尤其是在 `zsh` 里：

```sh
--signal 'led[3:0]=tb_led_test.led[3:0]:bus'
```

### 3. 使用信号列表文件

`examples/signals.txt` 示例：

```text
tb_led_test.sys_clk:bit
tb_led_test.rst_n:bit
timer=tb_led_test.dut.timer[31:0]:bus
led[3:0]=tb_led_test.led[3:0]:bus
```

调用：

```sh
./vcd-to-image \
  --vcd examples/lab1_led_test.vcd \
  --output out/lab1_from_file \
  --signals-file examples/signals.txt \
  --range 0ns..310ns
```

### 4. 使用 JSON 配置批量生成

```sh
./vcd-to-image --config examples/report_waves.json
```

最小配置示例：

```json
{
  "theme": "vivado-dark",
  "formats": ["png", "svg", "pdf", "json"],
  "waves": [
    {
      "title": "Lab1 LED流水灯",
      "vcd": "examples/lab1_led_test.vcd",
      "output": "out/lab1_led_test",
      "range": "0ns..310ns",
      "signals": [
        "sys_clk=tb_led_test.sys_clk:bit",
        "rst_n=tb_led_test.rst_n:bit",
        "timer=tb_led_test.dut.timer[31:0]:bus",
        "led[3:0]=tb_led_test.led[3:0]:bus"
      ]
    }
  ]
}
```

配置文件顶层字段会作为所有 `waves` 项的默认值；每个波形项里的字段可以覆盖默认值。

## 信号选择说明

### 手动选择信号

`--signal` 支持三种写法：

```text
path
label=path
label=path:kind
```

`kind` 支持：

- `auto`: 自动判断 bit/bus/clock
- `bit`: 按普通数字信号绘制
- `bus`: 按总线绘制并显示值
- `clock`: 按理想时钟绘制

示例：

```sh
--signal tb_led_test.sys_clk:bit
--signal reset=tb_led_test.rst_n:bit
--signal 'timer=tb_led_test.dut.timer[31:0]:bus'
```

### 自动选择信号

选择全部信号：

```sh
./vcd-to-image \
  --vcd examples/lab1_led_test.vcd \
  --output out/all_signals \
  --all-signals
```

按正则选择：

```sh
./vcd-to-image \
  --vcd examples/lab1_led_test.vcd \
  --output out/regex \
  --match 'clk|rst|led|timer'
```

按 scope 选择：

```sh
./vcd-to-image \
  --vcd examples/lab1_led_test.vcd \
  --output out/dut \
  --scope tb_led_test.dut
```

常用过滤参数：

```sh
--active-only
--changed-only
--exclude 'debug|tmp'
--max-signals 12
```

## 时间范围说明

使用 VCD tick：

```sh
--range 0..310000
```

使用时间单位：

```sh
--range 0ns..310ns
--start 4us --end 6us
```

围绕某个信号第一次活动截取窗口：

```sh
./vcd-to-image \
  --vcd examples/lab1_led_test.vcd \
  --output out/around_led \
  --around-signal tb_led_test.led[3:0] \
  --pre 50ns \
  --post 150ns \
  --signals-file examples/signals.txt
```

默认窗口策略：

- `--auto-window activity`: 根据所选信号活动范围自动决定
- `--auto-window full`: 使用整个 VCD 时间范围

## 样式和报告输出

### 主题

查看支持的主题：

```sh
./vcd-to-image themes
```

内置主题：

- `vivado-dark`
- `vivado-light`
- `report-light`
- `report-dark`
- `monochrome`
- `wavedrom`

### 覆盖主题颜色

```sh
./vcd-to-image \
  --vcd examples/lab1_led_test.vcd \
  --output out/custom_color \
  --signals-file examples/signals.txt \
  --theme report-dark \
  --theme-color signal=#9df36d \
  --theme-color text=#f8fafc
```

可覆盖的颜色键：

```text
bg panel panel2 panel3 grid grid2 text info signal signal2 muted success warning path
```

### PNG / PDF 尺寸和背景

```sh
--png-scale 1.25
--png-width 2400
--png-height 400
--dpi 144
--background white
```

用于 Word/WPS 报告时，推荐：

```sh
--format png,svg,pdf,json --png-scale 1.25 --dpi 144
```

### 总线值显示

```sh
--value-format hex
--value-format bin
--value-format dec
--value-format raw
```

限制总线值文字长度：

```sh
--max-value-chars 8
```

高密度概览图可以隐藏总线值：

```sh
--hide-data-labels
```

## 变量名清理

长层级变量名会影响报告排版，可以使用：

```sh
--label-mode auto
--label-mode leaf
--label-mode scope
--label-mode full
```

去掉统一前缀：

```sh
--label-strip-prefix tb_top.dut.
```

正则替换：

```sh
--label-replace 'dvi_encoder_m0\.=dvi.'
```

限制变量名长度：

```sh
--max-label-chars 32
```

## 分页和排序

信号很多时可以分页：

```sh
./vcd-to-image \
  --vcd examples/lab1_led_test.vcd \
  --output out/paged \
  --all-signals \
  --page-size 4 \
  --format png,svg,pdf,json
```

输出文件示例：

```text
out/paged_p01.png
out/paged_p02.png
```

排序方式：

```sh
--sort-signals selected
--sort-signals path
--sort-signals leaf
--sort-signals events
--sort-signals width
--reverse-signals
```

## 调试和校验

只预览最终选择的信号，不生成图片：

```sh
./vcd-to-image \
  --vcd examples/lab1_led_test.vcd \
  --dry-run \
  --signals-file examples/signals.txt \
  --range 0ns..310ns
```

批量生成报告时建议加严格模式，信号缺失或歧义会直接失败：

```sh
--strict
```

查看帮助：

```sh
./vcd-to-image --help
./vcd-to-image info --help
```

## 直接调用 Python 脚本

`vcd-to-image` 等价于：

```sh
python3 tools/vcd_to_image.py ...
```

底层兼容入口也可以直接调用：

```sh
python3 tools/vivado_wave.py \
  --vcd examples/lab1_led_test.vcd \
  --output out/compat \
  --title "compat" \
  --format png,svg,pdf,json \
  --signal sys_clk=tb_led_test.sys_clk:bit \
  --signal 'led[3:0]=tb_led_test.led[3:0]:bus'
```

## 作为 MCP Server 使用

VCD2Photo 也可以作为 MCP stdio server 使用，让支持 MCP 的客户端直接调用 VCD 波形查看和渲染能力。

MCP 入口：

- Linux/macOS: `./vcd-mcp`
- Windows: `vcd-mcp.bat`
- 跨平台 Python 方式: `python tools/vcd_mcp_server.py`
- 安装为 Python 命令后: `vcd2photo-mcp`

### MCP 暴露的工具

`vcd_info`

查看 VCD 信息，返回 timescale、时间范围、信号路径、位宽、事件数和 alias 数量。常用参数：

```json
{
  "vcd_path": "examples/lab1_led_test.vcd",
  "match": "timer|led|clk",
  "active_only": true,
  "max_signals": 20
}
```

`vcd_render`

渲染 VCD 波形图，返回生成文件路径。常用参数：

```json
{
  "vcd_path": "examples/lab1_led_test.vcd",
  "output_path": "out/mcp_lab1",
  "formats": ["png", "svg", "pdf", "json"],
  "theme": "vivado-dark",
  "range": "0ns..310ns",
  "title": "MCP Lab1",
  "signals": [
    "tb_led_test.sys_clk:bit",
    "tb_led_test.rst_n:bit",
    "timer=tb_led_test.dut.timer[31:0]:bus",
    "led[3:0]=tb_led_test.led[3:0]:bus"
  ]
}
```

`vcd_themes`

列出可用主题、总线显示格式和可覆盖的主题颜色键。

### Linux/macOS MCP 配置示例

把路径替换为你本机的绝对路径：

```json
{
  "mcpServers": {
    "vcd2photo": {
      "command": "/absolute/path/to/VCD2Photo/vcd-mcp",
      "args": []
    }
  }
}
```

也可以直接用 Python：

```json
{
  "mcpServers": {
    "vcd2photo": {
      "command": "python3",
      "args": [
        "/absolute/path/to/VCD2Photo/tools/vcd_mcp_server.py"
      ]
    }
  }
}
```

### Windows MCP 配置示例

把路径替换为你本机的绝对路径：

```json
{
  "mcpServers": {
    "vcd2photo": {
      "command": "python",
      "args": [
        "C:\\absolute\\path\\to\\VCD2Photo\\tools\\vcd_mcp_server.py"
      ]
    }
  }
}
```

也可以使用批处理入口：

```json
{
  "mcpServers": {
    "vcd2photo": {
      "command": "C:\\absolute\\path\\to\\VCD2Photo\\vcd-mcp.bat",
      "args": []
    }
  }
}
```

项目里提供了两个模板：

- `examples/mcp-config-linux.json`
- `examples/mcp-config-windows.json`

### 本地测试 MCP

Linux/macOS 可以直接测试初始化和工具列表：

```sh
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | ./vcd-mcp
```

测试 MCP 渲染：

```sh
python3 - <<'PY'
import json
import subprocess

messages = [
    {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0"}}},
    {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"vcd_render","arguments":{
        "vcd_path":"examples/lab1_led_test.vcd",
        "output_path":"out/mcp_lab1",
        "formats":["png","svg","json"],
        "range":"0ns..310ns",
        "signals":[
            "tb_led_test.sys_clk:bit",
            "tb_led_test.rst_n:bit",
            "timer=tb_led_test.dut.timer[31:0]:bus",
            "led[3:0]=tb_led_test.led[3:0]:bus"
        ]
    }}}
]

payload = "\n".join(json.dumps(item) for item in messages) + "\n"
result = subprocess.run(["./vcd-mcp"], input=payload, text=True, capture_output=True, check=True)
print(result.stdout)
PY
```

如果成功，会生成：

```text
out/mcp_lab1.png
out/mcp_lab1.svg
out/mcp_lab1.json
```

## 可选：安装为 Python 命令

Linux/macOS/Windows 都可以使用 pip 的 editable 安装：

```sh
python -m pip install -e .
```

安装后可以直接调用：

```sh
vcd-to-image info --vcd examples/lab1_led_test.vcd
vcd2photo-mcp
```

如果 Linux/macOS 提示找不到 `vcd-to-image` 或 `vcd2photo-mcp`，通常是用户级 pip 安装目录不在 `PATH`。可以临时这样调用：

```sh
~/.local/bin/vcd-to-image info --vcd examples/lab1_led_test.vcd
~/.local/bin/vcd2photo-mcp
```

或者把 `~/.local/bin` 加入 shell 配置：

```sh
export PATH="$HOME/.local/bin:$PATH"
```

## 常见问题

### `rsvg-convert: command not found`

安装 `librsvg2-bin`、`librsvg2-tools` 或 `librsvg`，具体包名取决于系统。

### `npx: command not found`

安装 Node.js 和 npm。Ubuntu/Debian 示例：

```sh
sudo apt-get install -y nodejs npm
```

### 第一次运行 `wavedrom-cli` 很慢

如果使用 `npx`，第一次运行可能会下载 `wavedrom-cli`。可以全局安装：

```sh
sudo npm install -g wavedrom-cli
```

### 找不到信号

先查信号路径：

```sh
./vcd-to-image info --vcd your.vcd --match 'part_of_name'
```

然后把完整路径复制到 `--signal`。

### 总线信号导致 shell 报错

给带 `[31:0]` 这类下标的参数加引号：

```sh
--signal 'data=tb.dut.data[31:0]:bus'
```

这在 `zsh` 中尤其重要，因为方括号可能会被当作 glob 模式。
