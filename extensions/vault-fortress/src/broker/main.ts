import { startBroker } from "./broker.js";

function parseArgs(){
  const args = process.argv.slice(2);
  const out: any = {};
  for (let i=0;i<args.length;i++){
    const a = args[i];
    if (a === "--db") out.db = args[++i];
    if (a === "--name") out.name = args[++i];
  }
  if (!out.db) {
    console.error("Usage: broker --db <path> [--name <pipeName>]");
    process.exit(2);
  }
  return out;
}

const { db, name } = parseArgs();
await startBroker({ dbPath: db, endpointName: name });
