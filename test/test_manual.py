from pathlib import Path

from yarl import URL

from manual import deserialize_ws, HTTPDumpFile


def test_deserialize_ws():
	url, frames = deserialize_ws(Path("fixtures/dump.ws"))
	assert url == "ws://example.com:63001/socket.io/?EIO=3&transport=websocket"
	assert frames == [
		(True, "2probe"),
		(False, "3probe"),
		(True, '{"manifest_version":3,"name":"Bookshelf-newtab"}'),
		(False, b"                                       DICM"),
	]

def test_deserialize_http():
	exchange = HTTPDumpFile.read_from(Path("fixtures/dump.http"))
	request_body = exchange.request_body()
	response_body = exchange.response_body()

	assert exchange.url == URL("https://qrgz.qnpacs.com/e/CustomImageServlet?tk=7")
	assert len(exchange.request_headers) == 15
	assert exchange.request_headers["sec-fetch-dest"] == "empty"
	assert request_body.startswith(b"requestType=")
	assert request_body.endswith(b"08540018&level=0")

	assert exchange.status == 200
	assert len(exchange.response_headers) == 8
	assert exchange.response_headers["p3p"] == 'CP=:"This is not a P3P policy!"'
	assert response_body == b"CLOHEADERZ01\x00\x00"
