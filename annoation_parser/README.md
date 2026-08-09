# Json解码器生成器

## 解码器分两级，主要针对C语言生成。

- lexer & parser 已完成
- Schema IR: 仅有一个框架
- Decode Plan IR： 未完成

## 生成目标

生成目标分为两种，一种为直接生成C语言解码代码，另一种则是生成VM bytecode，目前主力先实现直接C语言解码。


### VM bytecode定义（未完成）


```C
VM 定义
typedef uint32_t opcode;

struct {
    json_parser *parser;
    void *root;//  根对象
    stack *stack_ptr;
    void *max_stack_top;
    opcode *pc;
};

VM stack定义：
// 由于栈大小确定，且单线程执行，所以和C语言的栈规则不同，
// 函数退出后允许使用刚退出的函数的栈，这样就不需要返回值了
struct stack{
    void *base;  // 基址寄存器
    void *index; // 变址寄存器
    void *alloc_tail; // 分配器末尾,array时正好是 {ptr, size, cap}，obj时可以debug空间大小
    opcode *ret; // 返回地址，返回上一级的opcode
    union {
        uint64_t seen;
        uint64_t *seen_ptr;
    }
};

字节码定义：
UNDEFINED = 0x00000000 全0时一下就能看出来时什么问题

# 全都基于变址操作，
OFFSET (IMM)  # 可以更改index

# 解引用后会改变基址，也即 DEREF =>
{
    base = *index;
    index = base;
}

DEREF
// 基于当前index，先增加offset，再ensure size，最后deref解引用该变址
// 这条指令感觉只会需要在指针对象头前调用它
// 仔细想想其实只会和CALL连用，应该直接把这个整合到CALL里面去
ENSURE_DEREF_OFFSET (12SIZE, 12IMM)
{
    index = index + offset;
    if (*index == NULL) {
        *index = malloc(size);
        alloc_tail = *index + size;
    }
    base = *index;
    index = base;
}

# 全都不改变变址，基于index但不改变
ENSURE (SIZE)

STR_OFFSET_BOOL
STR_OFFSET_U8
STR_OFFSET_U16
STR_OFFSET_U32
STR_OFFSET_U64

STR_OFFSET_I8
STR_OFFSET_I16
STR_OFFSET_I32
STR_OFFSET_I64

STR_OFFSET_F64
STR_OFFSET_F32


ENSURE_STR_CAP
STR_STRING_BORROW
STR_STRING_CPY

NEXT

CALL // 要不要做一个 call.offset.ensure 做一个链接表， call table_i => offset, ensure_size, base, index = table[i]
RET
JMP(IMM)
J_TOKEN_EQ(TOKEN)
J_TOKEN_NE(TOKEN)
OBJ_DISPATCH(TABLE-OFFSET-IMM) 比较后立刻expect一个colon

ARR_RESERVE(SIZE) 只有扩容，offset上面已经有了

// 都是修改index的
LOAD_ROOT   index = root
LOAD_PARENT index = stack[-1].base;
RESET_INDEX index = base

FATAL
SKIP_VALUE
```