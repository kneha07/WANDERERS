// Windows check: server.js can send the photo bytes to Python on stdin (no temp file) and read one JSON line back.
//   node artifacts\star-fix\win\pipe.js <photo>
const { spawn } = require("child_process"), fs = require("fs"), path = require("path");
const { pickPython } = require("../../../fields");
const root = path.join(__dirname, "..", "..", ".."), t0 = Date.now();
const p = spawn(pickPython(root), ["-c", "import sys,io,json,pillow_heif;from PIL import Image;pillow_heif.register_heif_opener();d=sys.stdin.buffer.read();im=Image.open(io.BytesIO(d));print(json.dumps({'bytes':len(d),'size':im.size,'orient':im.info.get('original_orientation')}))"], { cwd: root });
let out = ""; p.stdout.on("data", (d) => (out += d)); p.stderr.on("data", (d) => process.stderr.write(d));
p.stdin.on("error", () => {}); p.stdin.end(fs.readFileSync(process.argv[2]));
p.on("close", (code) => console.log("python:", pickPython(root), "| exit", code, "|", out.trim(), "| file bytes", fs.statSync(process.argv[2]).size, "|", Date.now() - t0, "ms"));
