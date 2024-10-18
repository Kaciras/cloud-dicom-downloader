import { argv } from "node:process";
import { once } from "events";
import { dirname, join } from "path";
import { mkdirSync, writeFileSync } from "fs";

const url = new URL(argv[2]);
if (url.hostname !== "qr.szjudianyun.com") {
	throw new Error("Unsupported site");
}

const hospital_id = url.searchParams.get("a");
const study = url.searchParams.get("b");
const password = url.searchParams.get("c");

const outDir = `${hospital_id}-${study}`;

// 常量，是一堆 DICOM 的 TAG ID，由 b1u2d3d4h5a 分隔。
const tag = "0x00100010b1u2d3d4h5a0x00101001b1u2d3d4h5a0x00100020b1u2d3d4h5a0x00100030b1u2d3d4h5a0x00100040b1u2d3d4h5a0x00101010b1u2d3d4h5a0x00080020b1u2d3d4h5a0x00080030b1u2d3d4h5a0x00180015b1u2d3d4h5a0x00180050b1u2d3d4h5a0x00180088b1u2d3d4h5a0x00080080b1u2d3d4h5a0x00181100b1u2d3d4h5a0x00280030b1u2d3d4h5a0x00080060b1u2d3d4h5a0x00200032b1u2d3d4h5a0x00200037b1u2d3d4h5a0x00280030b1u2d3d4h5a0x00280010b1u2d3d4h5a0x00280011b1u2d3d4h5a0x00080008b1u2d3d4h5a0x00200013b1u2d3d4h5a0x0008103Eb1u2d3d4h5a0x00181030b1u2d3d4h5a0x00080070b1u2d3d4h5a0x00200062b1u2d3d4h5a0x00185101";

// 什么傻逼 qinniao，不会是北大青鸟吧？
const response = await fetch("http://qinniaofu.coolingesaving.com:63001/socket.io/?EIO=3&transport=polling&t=ooooooo");
if (!response.ok) {
	throw new Error(`Get token failed (${response.status})`);
}
let text = await response.text();
text = text.slice(text.indexOf("{"), text.lastIndexOf("}") + 1);
const { sid } = JSON.parse(text);

const ws = new WebSocket(`ws://qinniaofu.coolingesaving.com:63001/socket.io/?EIO=3&transport=websocket&sid=${sid}`, {
	headers: {
		Cookie: "io=" + sid,
	},
});

ws.onclose = () => console.log("\nWebSocket Closed");

function sendMessage(id, message) {
	ws.send(id + JSON.stringify(["sendMessage", message]));
}

async function getInfo() {
	ws.send("2probe");
	await once(ws, "message");
	ws.send("5");
	sendMessage(42, { type: "saveC", hospital_id, study, password });
	const [event] = await once(ws, "message");
	return JSON.parse(event.data.slice(2))[1];
}

function requestDICOM(id, index) {
	sendMessage(42, {
		hospital_id,
		study,
		tag,
		type: "hangC",
		ww: "",
		wl: "",
		series: id,
		series_in: index.toString(),
	});
}

await once(ws, "open");
const { series, series_dicom_number } = await getInfo();

let seriesIndex = 0;
let imageIndex = 1;

requestDICOM(series[seriesIndex], imageIndex);

ws.addEventListener("message", async ({ data }) => {
	if (typeof data === "string") {
		return; // 451 开头的回复消息，没什么用。
	}
	const id = series[seriesIndex];
	const file = join(outDir, id, imageIndex + ".dicom");

	console.log("Download: " + file);
	mkdirSync(dirname(file), { recursive: true });

	// 第一位 4 是 socket.io 添加的。
	writeFileSync(file, await data.slice(1).bytes());

	if (imageIndex >= series_dicom_number[id]) {
		imageIndex = 0;
		seriesIndex++;

		if (series[seriesIndex].startsWith("dfyfilm")) {
			seriesIndex++;
		}
		if (seriesIndex >= series.length) {
			return ws.close();
		}
	}
	requestDICOM(series[seriesIndex], ++imageIndex);
});

