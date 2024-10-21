import re


_illegal_path_chars = re.compile(r'[<>:"/\\?*|]')


def _to_full_width(match: re.Match[str]):
	if match[0] == ":": return "："
	if match[0] == "*": return "＊"
	if match[0] == "?": return "？"
	if match[0] == '"': return "'"
	if match[0] == '|': return "｜"
	if match[0] == '<': return "＜"
	if match[0] == '>': return "＞"
	if match[0] == "/": return "／"
	if match[0] == "\\": return "＼"


def pathify(text: str):
	"""
	为了用户易读，推荐使用影像的刻度名字作为目录名，但影像名可以有任意字符，而某些是文件名不允许的。
	这里就把非法字符替换为 Unicode 的宽字符，虽然有点别扭但并不损失易读性。
	"""
	return _illegal_path_chars.sub(_to_full_width, text.strip())
