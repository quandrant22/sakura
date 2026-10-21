// Запуск Electron из npm-скриптов без ELECTRON_RUN_AS_NODE: VS Code передаёт её дочерним процессам,
// и electron.exe с ней работает как Node (окно не открывается, «--quit» ничего не закрывает).
// node scripts/electron.mjs [аргументы electron]
import { spawn } from "node:child_process";
import { createRequire } from "node:module";

const electron = createRequire(import.meta.url)("electron");
const env = { ...process.env };
delete env.ELECTRON_RUN_AS_NODE;
const child = spawn(electron, process.argv.slice(2), { stdio: "inherit", env, windowsHide: false });
child.on("exit", (code) => process.exit(code ?? 0));
