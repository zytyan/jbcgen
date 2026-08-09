# annotation-parser

`annotation-parser` 从 C 头文件、Clang JSON AST 和文档注释生成 C11 JSON decoder 与 cleanup 实现。

## 分层

```text
Clang AST + documentation comments
               │
               ▼
           Schema IR
            ├── Decode Plan  ── C decoder
            ├── Release Plan ── C cleanup
            └── Encode Plan  ── future
```

Schema IR 不包含执行步骤。Decode Plan 与 Release Plan 独立从 Schema 构建，只通过稳定 Type ID 引用类型。三种现有 IR 都能打印为确定性、人类可读的调试文本；该文本不是序列化协议，不能反向解析。

## CLI

```text
annotation-parser INPUT.h -o OUTPUT.c \
  [--clang CLANG] [--include HEADER] \
  [--dump-ir schema|decode|release|all] \
  [-- <clang 参数>...]
```

开发目录中可直接运行：

```sh
PYTHONPATH=src python3 -m annotation_parser ../example/example.h \
  -o example_json.c --include example/example.h -- -I ../runtime
```

生成失败时不会覆盖已有输出文件。Clang 和注解错误包含文件、行、列。

## 注解

- `@jsonStruct`：允许作为公开生成入口的结构体。
- `@jsonDecode`：标记 `bool function(json_parser *, T *)` 声明。
- `@jsonCleanup`：标记 `void function(json_allocator *, T *)` 声明。
- `@json(...)`：设置字段行为。

字段参数：

- `key=name`：主 JSON key。
- `altkey=name`：别名，可重复；任一别名与主键共享重复检测和 required 状态。
- `required`：key 必须出现且值不能为 null；`{}`、`[]` 和空字符串合法。
- `min`、`max`：含边界数值限制。
- `minlen`、`maxlen`：解码后字符串字节数或数组元素数限制。
- `type=array, len=countField`：将 `T *` 解释为动态数组。
- `len=countField`：为固定数组保存实际元素数。
- `flatten`：将值结构体字段展开到父对象；不能与 `required` 组合。
- `omitempty`：保存在 Schema 中，当前 decoder 不使用。

未知参数、重复的单值参数、不适用的参数组合和 JSON key 冲突都会在生成期报错。动态数组的伴随长度字段不作为独立 JSON key。

## 支持的 C 类型

- `_Bool` / `bool`
- LP64 下的有符号和无符号基础整数及 typedef
- `float`、`double`
- 数值 enum
- `char *`、`char[N]`
- 固定 `T[N]`
- 值结构体、结构体指针和递归指针
- 带 `len` 的动态 `T *` 数组

暂不支持 union、位域、函数指针、柔性或零长 C 数组。

## 解码与所有权

- 调用 decode 前，输出对象必须全零；重复使用前先 cleanup。
- 未知字段跳过，重复已知字段报错，缺失的非 required 字段保持零值。
- required key 缺失与 required 值为 null 使用不同的结构化错误码。
- 非 required 的 `char *`、动态数组和结构体指针接受 null，且不分配。
- 动态数组使用延迟分配；`null` 和 `[]` 均保持 `NULL + 0`，只有第一个元素出现后才申请容量。
- 空 JSON 字符串分配一个 NUL 字节，以区别于 null。
- `char *` 与 `char[N]` 拒绝嵌入 NUL；字符串长度按解码后的 UTF-8 字节计算。
- 失败时由独立 Release Plan 生成的 helper 深度回滚并清零；cleanup 可重复调用。

## 测试

```sh
cd annotation_parser
PYTHONPATH=src python3 -m unittest discover -s tests -v

cd ../runtime
cmake -S . -B build -DBUILD_TESTING=ON
cmake --build build
ctest --test-dir build --output-on-failure
```

Runtime 的 CMake 测试会生成、编译并执行 `example/example.h` 对应的 decoder。
