"""CLI 文件修改结果展示测试。"""

import json

from minicode.cli import _format_tool_result


def test_edit_result_is_grouped_for_human_reading() -> None:
    """文本模式应只展示文件路径和实际 diff。"""
    content = json.dumps(
        {
            "path": "app.py",
            "details": {
                "operation": "edit",
                "source": "return a - b",
                "updated": "return a + b",
                "diff": "-return a - b\n+return a + b\n",
            },
        }
    )
    output = _format_tool_result(content)
    assert "文件已修改：app.py" in output
    assert "[源码]" not in output
    assert "[修复归因]" not in output
    assert "-return a - b" in output
