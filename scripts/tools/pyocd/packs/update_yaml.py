"""扫描 packs/ 目录，重新生成 pyocd.yaml 里的 pack 清单（维护用，非日常）。"""

import os

with open("../pyocd.yaml", mode="w") as f:
    f.write("""
pack:
""")
    for file in os.listdir():
        if str(file).endswith(".pack"):
            f.write("  - ./packs/" + str(file) + "\n")
