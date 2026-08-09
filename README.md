# jbcgen

从C结构体+文档注释生成C语言json解码器的工具。


## Python 部分
Python部分用于生成解析器、字节码和读取对应的文档属性，预计使用`clang -Xclang -dump-ast=json` 获取。但时机成熟后也可以使用libtooling编译后获取。

当前假设目标架构为64位，不同整数位数固定。换用libtooling后可以从`compile_commands.json`中获得实际整数大小。

### annoation_parser 
具体内容见目录内README。

## C部分
用于解码Json的运行时，基本上是一个一遍扫描的pull API模式的 Json扫描器，有部分扩展能力。