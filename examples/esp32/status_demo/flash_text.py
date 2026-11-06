"""Keep fixed Xu text in instruction immediates, preserving ESP32 radio DRAM.

Only copied application/codec sources are transformed. Original sources stay
readable; generated Xu owns each decoded string through normal language rules.
"""
from pathlib import Path
import json
import re

TOKENS = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"')


def compact_text(paths, module, output):
    values = []
    indices = {}

    def replace(match):
        spelling = match.group(0)
        if not spelling.startswith('"'):
            return spelling
        value = json.loads(spelling)
        if len(value.encode("utf-8")) <= 4:
            return spelling
        if value not in indices:
            indices[value] = len(values)
            values.append(value)
        return f'_flash_text({len(value.encode("utf-8"))},_flash_word_{indices[value]})'

    for path in paths:
        path = Path(path)
        path.write_text(TOKENS.sub(replace, path.read_text()))

    def branch(words, start=0, indent='    '):
        if len(words) == 1:
            return indent + '<< ' + hex(words[0]) + '\n'
        half = len(words) // 2
        return (indent + f'if i < {start + half} {{\n' +
                branch(words[:half], start, indent + '    ') + indent + '} else {\n' +
                branch(words[half:], start + half, indent + '    ') + indent + '}\n')

    generated = [f"@{module}\n\n// Generated fixed text; typed readers keep constants in instruction storage.\n", """
fn _flash_text(count int, word fn(int) int) string {
    $s := make_string(count)
    for i in 0:(count + 3) / 4 {
        v := word(i)
        for j in 0:4 { if i * 4 + j < count { s[i * 4 + j] = (v >> (j * 8)) & 255 } }
    }
    << s
}
"""]
    for index, value in enumerate(values):
        data = value.encode('utf-8')
        words = [int.from_bytes(data[i:i + 4].ljust(4, b'\0'), 'little') for i in range(0, len(data), 4)]
        generated.append(f'fn _flash_word_{index}(i int) int {{\n' + branch(words) + '}\n')
    Path(output).write_text('\n'.join(generated))
    return Path(output)
