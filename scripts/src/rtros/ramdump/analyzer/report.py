"""报告输出：把分析结果渲染成自包含 HTML。"""

from __future__ import annotations

import os
from datetime import datetime

# Optional imports
from rtros.ramdump.analyzer.arm_backtrace import format_backtrace
from rtros.ramdump.analyzer.exception_decoder import decode_fault_registers, get_fault_summary
from rtros.ramdump.analyzer.model import RamdumpAnalysis


def generate_html_report(analysis: RamdumpAnalysis) -> str:
    """Generate an HTML analysis report."""
    fault_summary = get_fault_summary(analysis.exception.cfsr, analysis.exception.hfsr)

    backtrace_html = "<pre>" + format_backtrace(analysis.backtrace) + "</pre>"

    # Thread table
    thread_rows = ""
    for t in analysis.threads:
        thread_rows += (
            f"<tr>"
            f"<td>{t.name}</td>"
            f"<td><code>0x{t.sp:08X}</code></td>"
            f"<td><code>0x{t.stack_addr:08X}</code></td>"
            f"<td>{t.stack_size}</td>"
            f"<td>{t.priority}</td>"
            f"<td>{t.state_name}</td>"
            f"</tr>\n"
        )

    e = analysis.exception
    # 异常记录无效时 registers 是 None（例如镜像里没有魔数签名），此处不能直接解引用
    pc_text = f"0x{e.registers.pc:08X}" if e.registers else "N/A"
    pc_symbol = f" ({analysis.symbols.get(e.registers.pc, 'unknown')})" if e.registers else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RAM Dump Analysis Report</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         max-width: 1100px; margin: 20px auto; padding: 0 20px;
         background: #f5f5f5; color: #333; }}
  h1 {{ color: #c0392b; border-bottom: 3px solid #c0392b; padding-bottom: 10px; }}
  h2 {{ color: #2c3e50; border-bottom: 2px solid #bdc3c7; padding-bottom: 5px; margin-top: 30px; }}
  .card {{ background: white; border-radius: 8px; padding: 20px; margin: 15px 0;
           box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
  .fault-box {{ background: #ffeaa7; border-left: 4px solid #fdcb6e; padding: 12px 16px;
                border-radius: 4px; margin: 10px 0; }}
  .error-box {{ background: #fab1a0; border-left: 4px solid #e17055; padding: 12px 16px;
                border-radius: 4px; margin: 10px 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
  th {{ background: #2c3e50; color: white; padding: 8px 12px; text-align: left; }}
  td {{ padding: 6px 12px; border-bottom: 1px solid #ddd; }}
  tr:hover {{ background: #f8f9fa; }}
  pre {{ background: #2d3436; color: #dfe6e9; padding: 15px; border-radius: 6px;
         overflow-x: auto; font-size: 13px; line-height: 1.5; }}
  code {{ background: #dfe6e9; padding: 1px 4px; border-radius: 3px; font-size: 90%; }}
  .meta {{ color: #636e72; font-size: 14px; }}
  .footer {{ margin-top: 40px; padding-top: 10px; border-top: 1px solid #ddd;
             color: #b2bec3; font-size: 12px; text-align: center; }}
</style>
</head>
<body>

<h1> RAM Dump Analysis Report</h1>

<div class="meta">
  <p>Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
  <p>SRAM: {os.path.basename(analysis.sram_path) if analysis.sram_path else "N/A"}
     | CCM: {os.path.basename(analysis.ccm_path) if analysis.ccm_path else "N/A"}
     | ELF: {os.path.basename(analysis.elf_path) if analysis.elf_path else "N/A"}</p>
</div>

<!-- Fault Summary -->
<h2> Fault Summary</h2>
<div class="card">
  <div class="error-box">
    <strong>Fault Type:</strong> {e.fault_name}<br>
    <strong>Summary:</strong> {fault_summary}<br>
    <strong>Thread:</strong> {e.thread_name} (tick: {e.tick})<br>
    <strong>PC:</strong> <code>{pc_text}</code>{pc_symbol}
  </div>

  <table>
    <tr><th>Register</th><th>Value</th><th>Description</th></tr>
    <tr><td>CFSR</td><td><code>0x{e.cfsr:08X}</code></td><td>Configurable Fault Status</td></tr>
    <tr><td>HFSR</td><td><code>0x{e.hfsr:08X}</code></td><td>HardFault Status</td></tr>
    <tr><td>MMFAR</td><td><code>0x{e.mmfar:08X}</code></td><td>MemManage Fault Address</td></tr>
    <tr><td>BFAR</td><td><code>0x{e.bfar:08X}</code></td><td>BusFault Address</td></tr>
    <tr><td>HW Frame</td><td><code>0x{e.hw_frame_ptr:08X}</code></td><td>Hardware stacked frame pointer</td></tr>
    <tr><td>Thread SP</td><td><code>0x{e.current_thread_sp:08X}</code></td><td>Stack pointer at crash</td></tr>
  </table>
</div>

<!-- Fault Decode -->
<h2> SCB Register Decode</h2>
<div class="card">
  <pre>{decode_fault_registers(e.cfsr, e.hfsr, e.mmfar, e.bfar)}</pre>
</div>

<!-- Call Stack -->
<h2> Call Stack Backtrace</h2>
<div class="card">
  {backtrace_html}
</div>

<!-- Thread List -->
<h2> Thread List</h2>
<div class="card">
  <table>
    <tr>
      <th>Name</th><th>SP</th><th>Stack Base</th>
      <th>Stack Size</th><th>Priority</th><th>State</th>
    </tr>
    {thread_rows}
  </table>
</div>

<div class="footer">
  RT-Thread Ramdump Analyzer &mdash; Generated report
</div>

</body>
</html>"""
