import codecs
import enum
import re
from dataclasses import dataclass
from pprint import pprint


class TokenKind(enum.Enum):
    NormalString = 0
    NakedString = 1
    Punc = 2
    Eof = 3


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    val: str

    def __repr__(self) -> str:
        return f"{self.kind.name}({self.val!r})"


def _tokenize_str(text: str):
    quote = text[0]
    i = 1
    res: list[str] = []
    while i < len(text):
        if text[i] == quote:
            i += 1
            return "".join(res), i
        elif text[i] != "\\":
            res.append(text[i])
            i += 1
            continue
        # 下面是 text[i] == '\\' 的逻辑
        if i + 2 >= len(text):
            break
        if text[i + 1] in "'\"`":
            res.append(text[i + 1])
            i += 2
        else:
            try:
                res.append(codecs.decode(text[i : i + 2], "unicode_escape"))
            except UnicodeDecodeError:
                raise SyntaxError(f"非法转义: {text}")
            i += 2
    raise SyntaxError(f"不完整的字符串: {text}")


def _tokenize_raw_str(text: str, m: re.Match[str]):
    # 学习一波rust r###"""### ==> "\""，不过考虑到要塞到C语言字符串里，
    # 所以也允许单引号和反引号作为字符串定界符
    # ChatGPT 看不懂这个逻辑，总是左脑攻击右脑，最后发现是对的
    pattern = m.group()
    end_pattern = pattern[1:][::-1]
    idx = text[len(pattern) :].find(end_pattern)
    if idx == -1:
        raise SyntaxError(f"不完整的原始字符串: {text}")
    idx += len(pattern)
    return text[len(pattern) : idx], idx + len(end_pattern)


def tokenize(text: str) -> list[Token]:
    result: list[Token] = []
    puncs = "(){}[]=,@$"
    esc_puncs = re.escape(puncs)
    while text:
        if text[0] in puncs:
            result.append(Token(TokenKind.Punc, text[0]))
            text = text[1:]
        elif m := re.match(r"""[\'\"`]""", text):
            # 处理普通字符串
            string, idx = _tokenize_str(text)
            result.append(Token(TokenKind.NormalString, string))
            text = text[idx:]
        elif m := re.match(r"""([rR]\#*)[\'\"`]""", text):
            # 处理raw字符串
            raw_string, idx = _tokenize_raw_str(text, m)
            result.append(Token(TokenKind.NormalString, raw_string))
            text = text[idx:]
        elif m := re.match(rf"""[^\s='\`\"{esc_puncs}]+""", text):
            # 处理裸字符串
            result.append(Token(TokenKind.NakedString, m.group()))
            text = text[m.end() :]
        elif m := re.match(r"\s+", text):
            text = text[m.end() :]
        else:
            raise SyntaxError(f"不认识的token {text}")
    result.append(Token(TokenKind.Eof, ""))
    return result


def main():
    res = tokenize(
        r""" key=id, offset=0, m=r`abc\ndefg` s='id\n2' altkey=userid, altkey=user-id, altkey=user_id """
    )
    pprint(res)
    res = tokenize(r""" key=../../len, offset=0, m=r`abcdefg` s='id2' """)
    res = tokenize(r"""r`abcdefg`abc(def 中文怎么算？""")
    pprint(res)


if __name__ == "__main__":
    main()
