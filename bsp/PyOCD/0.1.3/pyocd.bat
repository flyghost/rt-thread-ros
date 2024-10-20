
::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
:: ..\..\PyOCD\0.1.3\pyocd.bat flash --target=STM32F407VE --erase=auto --frequency=1000000 rtthread.bin
::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::

:: 关闭命令行回显，以减少不必要的输出信息
@echo off
setlocal enabledelayedexpansion
echo ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

:: 获取所有参数
set "args=%*"

:: 检查是否有参数
if "%args%"=="" (
    echo 没有参数传递给 pyocd.exe
    goto :eof
)

:: 获取最后一个参数
for %%A in (%args%) do set "lastparam=%%A"

:: 打印最后一个参数
echo lastparam: %lastparam%

:: 将最后一个参数转换为绝对路径
for %%A in ("%lastparam%") do set "abs_lastparam=%%~fA"

:: 打印转换后的最后一个参数
echo lastparam: %abs_lastparam%

:: 构建新的参数列表，将最后一个参数替换为绝对路径
set "newargs="
for %%A in (%args%) do (
    if not "%%A"=="%lastparam%" (
        set "newargs=!newargs! %%A"
    ) else (
        set "newargs=!newargs! %abs_lastparam%"
    )
)

:: 去除新参数列表开头的空格
set "newargs=%newargs:~1%"

:: 打印所有参数
echo param: !newargs!

:: 打印当前路径
echo current path : %CD%
:: 保存当前路径
pushd %CD%
:: 切换到批处理文件所在的目录，确保后续操作在正确路径执行
cd /D %~dp0
:: 打印切换后的路径
echo downlaod path: %CD%

:: 调用pyocd.exe工具，并将所有传入的参数原样传递给它
:: pyocd.exe %*
pyocd.exe !newargs!

:: 返回保存的路径
popd

:: 打印返回后的路径
echo download end

echo ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
