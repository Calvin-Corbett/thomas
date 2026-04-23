import fs from "node:fs";
import path from "node:path";

function walk(dir: string, out: string[]){
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })){
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(p, out);
    else if (entry.isFile() && entry.name.endsWith(".ts")) out.push(p);
  }
}

const files: string[] = [];
walk(path.join(process.cwd(), "src"), files);

let bad = 0;
for (const f of files){
  const s = fs.readFileSync(f, "utf8");
  // flag suspicious literal truncations
  const suspicious = /req\.\.\.|\breturn\s+\.{3}|\bconst\s+\w+\s*=\s*\.{3}/.test(s);
  if (suspicious){
    console.error("[quickcheck] suspicious ellipsis in", f);
    bad++;
  }
}
if (bad) process.exit(2);
console.log("[quickcheck] ok");
