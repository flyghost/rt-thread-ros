# Trace32 2021 PRACTICE Script 编码规范

适用于: Trace32 Debugger 2021 版本 (Lauterbach)

---

## 一、表达式语法

### 1.1 操作符两侧禁止空格

- 错误: `&a = &b + 4`
- 正确: `&a=&b+0x4`
- 规则: 赋值(`=`)、算术(`+`、`-`)、比较(`==`、`!=`、`>`、`<`、`>=`) 左右均不能有空格

### 1.2 支持的算术操作符有限

- 支持: `+`, `-`
- 不支持: `*`, `/`, `%`
- 规则: 算术运算中不可用括号分组。但 `IF`/`WHILE` 条件中 `()` 可用作比较表达式分组
- (注: `*` 在某些上下文可能解析为符号通配符,不可用于乘法运算)
- 替代方案: 用循环累加替代乘法,或用手动计算常量替代

### 1.3 比较操作符

- 支持: `==`, `!=`, `>`, `<`, `>=`, `<=`, `&&`
- **CRITICAL**: `>`, `>=`, `!=`, `&&` 必须包裹在括号内,否则 `>` 被解析为 IO 重定向

```cmm
; 错误: IF &a>&b           (解析为 IO 重定向)
; 正确: IF (&a>&b)         (括号包裹,正确解析)
; 错误: IF &a!=0x0         (裸 != 解析异常)
; 正确: IF (&a!=0x0)       (括号包裹,正确解析)
; 正确: IF (("&s"!="")&&(&n>0))  (多层括号包裹复合条件)
```

- **CRITICAL**: `!` 取反操作符在 GOSUB 子程序中不可用（即使加括号）。替代: `IF sYmbol.EXIST() (...) ELSE (...)` 反转逻辑
- **UNTESTED**: `||` 逻辑或操作符 (请使用嵌套 IF-ELSE 替代)

---

## 二、数值字面量

### 2.1 在 WHILE 循环体内,必须使用十六进制字面量

```cmm
; 错误: &entry_addr=&entry_addr+4   (十进制在 WHILE 体内解析异常)
; 正确: &entry_addr=&entry_addr+0x4
; 错误: &i=&i+1
; 正确: &i=&i+0x1
```

规则: WHILE 循环体内的所有数值必须用 `0x` 前缀的十六进制格式

### 2.3 DO 上下文中的数值字面量强制按十六进制解析 (CRITICAL)

```cmm
; 错误: IF (&_ev==14)      (DO 文件内, 14 被解析为 0x14 = 20)
; 错误: IF (&_ev==22)      (DO 文件内, 22 被解析为 0x22 = 34)
; 正确: IF (&_ev==0xE)     (显式 0x 前缀, 14 decimal)
; 正确: IF (&_ev==0x16)    (显式 0x 前缀, 22 decimal)
```

规则: 通过 `DO` 加载的 `.cmm` 文件中, 所有数值字面量默认按**十六进制**解析。
这意味着 `10` 被解析为 `0x10` (16), `20` 被解析为 `0x20` (32)。
0-9 因十进制与十六进制相同而不会暴露问题, 但 >=10 的值必须使用显式 `0x` 前缀的十六进制格式。

根因: Trace32 2021 PRACTICE 解释器在 `DO` 加载的文件上下文中, 对所有裸数值字面量默认采用十六进制解析。

```cmm
; 错误: 0x8014DAB8 + 0x4
; 正确: 0x8014DAB8+0x4 (但也是错误用法,见 3.2)
```

---

## 三、Data 访问 (D: 表达式)

### 3.1 不支持 D: 后跟算术表达式

```cmm
; 错误: Data.Long(D:g_usbe_trace_ctrl + 0)
; 错误: Data.Long(D:&base + 0)
```

规则: `D:` 后只能是单一符号名或单一宏变量,不能包含任何运算

### 3.2 不支持 D: 后跟硬编码地址 (除非地址没有歧义)

```cmm
; 错误: Data.Long(D:0x8014DAB8 + 0)
```

规则: 硬编码地址可能被解析器混淆。如果必须用硬编码地址,先把地址赋给宏变量,再用 `D:&var`

---

## 四、宏变量地址运算

### 4.1 地址步进的标准模式 (参考 show_thread.cmm 验证通过)

```cmm
&entry_addr=&history
&index=Data.Byte(D:&entry_addr)       ; 读数据
&entry_addr=&entry_addr+0x4           ; 步进地址 (十六进制、无空格)
&time=Data.Long(D:&entry_addr)        ; 读下一个字段
&entry_addr=&entry_addr+0x4           ; 继续步进
&event=Data.Long(D:&entry_addr)       ; 读最后一个字段
&entry_addr=&entry_addr+0x4           ; 指向下一条记录头部
```

关键点:
- 直接用 `&entry_addr` 步进,不要引入临时变量 `&a`
- 临时变量读 `D:&a` 会产生错误数据 (可能是指针/引用语义问题)
- 必须严格按照"读 → 加偏移 → 读 → 加偏移"的顺序

### 4.2 不要引入中间变量来保存偏移后的地址

```cmm
; 错误: &a=&entry_addr+0x4  然后  Data.Long(D:&a)
; 正确: &entry_addr=&entry_addr+0x4  然后  Data.Long(D:&entry_addr)
```

---

## 五、字符串处理

### 5.1 字符串读取

- `Data.STRing(D:&addr)` -- 从目标内存地址读取 C 字符串
- `Var.String(var)` -- 获取变量的字符串值 (用于结构体字段)
- 注意: `FORMAT.TOCHAR()` 函数不存在于 2021 版本

### 5.2 空字符串判断

| 方式 | 示例 | 说明 |
|------|------|------|
| 推荐 | `IF (("&var"==""))` | 双层括号直接比较,最可靠 |
| 备选 | `IF (&var==0)` | 数字哨兵（do 传参场景推荐） |
| 不推荐 | `IF STRing.LEN("&var")==0` | 某些上下文可能失效 |

注意: 字符串比较在 IF 中必须用双层括号 `(("..."=="..."))`,否则解析异常

### 5.3 字符串比较

```cmm
IF (("&str1"=="&str2"))  ; 字符串比较必须双层括号
```

### 5.4 字符串下标索引不支持

```cmm
; 错误: "&str"[0]              (取首字符,解析异常)
; 错误: "&str"[1]              (取第二个字符)
```

替代: 用 `sYmbol.EXIST()` 等其他方式判断,避免字符级操作。或用 `STRing.MID()` 取子串（待验证）

---

## 六、符号与 DWARF 调试信息

### 6.1 sYmbol.ADDRESS() 函数不存在

```cmm
; 替代方案: 用 sYmbol.EXIST() 校验符号存在后,直接使用硬编码基地址
IF !sYmbol.EXIST(g_usbe_trace_ctrl)
(
    PRINT "ERROR: symbol not found"
    ENDDO
)
```

### 6.2 LOCAL/static 符号无法通过 Var.Value 解析 DWARF HLL 成员访问

- 错误: `Var.Value(g_usbe_trace_ctrl.history)` (对于 LOCAL/static 符号,返回 0 或无效值)
- 规则: LOCAL 符号 (文件作用域 static 变量) 的 DWARF 信息在 HLL 表达式求值中不可靠。必须通过硬编码基地址 + 结构体布局偏移量手动读取各字段。

### 6.3 获取符号地址的方法

```cmm
&base=ADDRESS.OFFSET(g_usbe_trace_ctrl)   ; 已确认可用
```

备选: `readelf -s elf | grep symbol` 获取地址后硬编码

---

## 七、流程控制

### 7.1 WHILE 循环

```cmm
WHILE &i<&show_num
(
    ...       ; 循环体
    &i=&i+0x1 ; 递增必须用十六进制
)
```

注意:
- WHILE 条件中的变量不需要 `"&"` 转义
- 循环体内部所有数值必须是 `0x` 前缀十六进制
- 不支持递减到零作为条件: `WHILE &cnt>0` (实际上有时可行)

### 7.2 IF 条件语句

```cmm
IF &i==&pos
    &mark=" <-- next"
ELSE
    &mark=""
```

### 7.3 ELSE IF 不可靠,必须用嵌套写法

```cmm
; 错误: IF (...) (...) ELSE IF (...) (...)   (字符串比较时解析异常)
; 正确: IF (...) (...) ELSE ( IF (...) (...) ELSE (...) )
```

规则: ELSE IF 连写配合字符串双层括号时不可靠,统一拆成 ELSE 块内嵌 IF

例外: 纯数值比较的 `ELSE IF &_type==0x31` 有时可工作,但仍建议用嵌套写法

---

## 八、PRINTF 格式化

### 8.1 PRINTF 中字符串参数必须用引号包裹宏变量

```cmm
; 错误: PRINTF "%s" &event_str
; 正确: PRINTF "%s %s" "&event_str" "&mark"
```

规则: 字符串类型的宏变量在 PRINTF 中必须写成 `"&varname"`

### 8.2 数字参数不需要引号

```cmm
; 正确: PRINTF "%3d %08d" &i &time
```

### 8.3 PRINT 不支持格式化,直接输出字符串

```cmm
PRINT "================================================================="
```

---

## 九、脚本参数 (ENTRY) 与 do 传参

### 9.1 do 传参禁止使用 "" 空字符串字面量

```cmm
; 错误: do script.cmm param1 "" param3  ("" 导致参数错位)
; 正确: do script.cmm param1 0 param3   (用 0 作为哨兵值)
```

**根因**: `do` 无法正确传递空字符串 `""`。展开后后续所有参数向前偏移一位,目标脚本 `ENTRY` 捕获错误值,导致 `IF (&show_num==0)` 变成 `IF (==0)`

### 9.2 可选参数默认值判断

- 推荐: `IF (&param==0)` -- 用数字哨兵 0 判断未传参
- 备选: `IF (("&param"==""))` -- 直接判空（do 传参场景不可靠）

```cmm
ENTRY &show_num
IF (&show_num==0)
    &show_num=&max         ; 未传参时用默认值
```

### 9.3 ENDDO 返回值禁止空字符串

```cmm
; 错误: ENDDO ""           (空串导致调用者 do 传参错位)
; 正确: ENDDO "SELECTED"   (用非空 sentinel 占位)
```

ENDDO 返回多个值,调用者用 ENTRY 捕获:

```cmm
do selector.cmm
ENTRY &sel_symbol &sel_type
IF (("&sel_symbol"=="SELECTED"))
    ; 用户做了选择
```

### 9.4 GLOBAL 变量 -- 跨脚本传递数值的最佳方式

适用场景: 当字符串格式转换不可靠（EVAL/VAL 不可用）,用 GLOBAL 变量直接传递数值地址

```cmm
; === 脚本 A (selector) ===
GLOBAL &g_my_value          ; 必须在脚本顶层声明（GOTO main 之前）
                            ; 不能在函数体内声明
                            ; 不能穿插在 LOCAL 声明之间

  GOTO main

main:
  LOCAL &symbol ...
  ...
  &g_my_value = &_cur       ; 赋值数值,无需字符串转换

; === 脚本 B (viewer) ===
GLOBAL &g_my_value          ; 同样在脚本顶层声明
  ...
  &base = &g_my_value       ; 直接读取数值
```

---

## 十、已知函数支持状态 (Trace32 2021)

### 可用

| 函数 | 说明 |
|------|------|
| `sYmbol.EXIST()` | 检查符号是否存在 (GOSUB 子程序内不可用) |
| `sYmbol.FUNCTION()` | 根据地址解析函数名 |
| `ADDRESS.OFFSET()` | 获取符号起始地址 |
| `Data.Long()`, `Data.Byte()`, `Data.Word()` | 目标内存读取 |
| `Data.STRing()` | 目标内存字符串读取 |
| `STRing.LEN()` | 宏变量字符串长度 |
| `FORMAT.Hex(8, val)` | 数值转 hex 字符串 (参数: width, value) |
| `FORMAT.Decimal(10, val)` | 数值转十进制字符串 |
| `OS.PPD()` | 获取当前目录 |
| `Var.Value()` | 仅对全局非 static 符号的 HLL 成员访问可靠 |
| `PRINT`, `PRINTF` | 输出 |
| `ENTRY`, `LOCAL`, `GLOBAL` | 变量声明 |

### 不可用

| 函数/特性 | 说明 | 替代方案 |
|-----------|------|----------|
| `sYmbol.ADDRESS()` | 不存在 | 用 `ADDRESS.OFFSET()` |
| `sYmbol.BEGIN()` | 不存在 | 用 `ADDRESS.OFFSET()` |
| `FORMAT.TOCHAR()` | 不存在 | -- |
| `EVAL()` | 不可用 (hex 字符串转数值失败) | 用 GLOBAL 变量传数值 |
| `VAL()` | 不可用 (十进制字符串转数值失败) | 用 GLOBAL 变量传数值 |
| `"str"[n]` | 字符串下标索引不支持 | 用 `sYmbol.EXIST()` 等替代 |
| `Var.String(numeric)` | 数字转字符串不可靠 | -- |
| `*` 乘法操作符 | 不支持 | 循环累加 |
| `/` 除法操作符 | 不支持 | -- |
| `()` 括号分组 | 不支持 | -- |

### CRITICAL 注意事项

1. **EVAL/VAL 不可用**: 无法将字符串转回数值。跨脚本传递地址必须用 GLOBAL 变量 (见 9.4),不要尝试 hex/decimal 字符串+EVAL/VAL 方案。

2. **sYmbol.EXIST() 在 GOSUB 子程序中不可用**: 必须将符号检查逻辑放在 main 中,或将结果通过变量传入子程序。
